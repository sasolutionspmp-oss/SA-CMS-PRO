"""Atomic human AP practice actions with audited repeatability receipts.

Only three fixed bill commands are reachable.  Current person authority is
checked before receipt lookup; committed outcomes replay before a current
record version or preflight token can reject the original review.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from uuid import UUID

from .ap_contract import APRefusal
from .core.api_receipts import APIActionReceipts, APIReceiptIntegrityError
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow
from .core.money import money
from .domain.bills import BillError
from .service import CipherError

CONTRACT_VERSION = "cipher.ap-practice.v1"
ACTIONS = frozenset(("bill.requestApproval", "bill.approve", "bill.post"))


def _refusal(status: int, code: str, message: str, target: str | None = None) -> APRefusal:
    return APRefusal(status, code, message, target)


class APActionRunner:
    def __init__(self, cipher, contract, preflight):
        self.cipher = cipher
        self.contract = contract
        self.preflight = preflight
        self.receipts = APIActionReceipts(cipher.db, cipher.audit)

    @contextmanager
    def _transaction(self):
        with self.cipher.db.transaction() as conn:
            savepoint = new_id("ap_action")
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:
                    conn.execute(f"ROLLBACK TO {savepoint}")
                raise
            finally:
                if conn.in_transaction:
                    conn.execute(f"RELEASE {savepoint}")

    def _shape(self, action: str, resource_id: str, body: dict[str, Any], key: str, if_match: str) -> tuple[str, dict[str, Any]]:
        if action not in ACTIONS or not isinstance(resource_id, str) or not resource_id or len(resource_id) > 160:
            raise _refusal(422, "invalid_action", "Choose a supported bill action.")
        try:
            normalized_key = str(UUID(key)) if isinstance(key, str) and len(key) == 36 else None
        except (ValueError, AttributeError):
            normalized_key = None
        if normalized_key is None or normalized_key != key.casefold():
            raise _refusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.")
        if not isinstance(if_match, str) or not if_match or len(if_match) > 256:
            raise _refusal(422, "missing_record_version", "Supply the record version reviewed for this action.")
        fields = {"fingerprint", "periodId", "reason"} if action == "bill.post" else {"fingerprint"}
        if not isinstance(body, dict) or set(body) != fields:
            raise _refusal(422, "invalid_body", "The action body must contain exactly the documented review fields.")
        if not isinstance(body["fingerprint"], str) or not body["fingerprint"] or len(body["fingerprint"]) > 256:
            raise _refusal(422, "invalid_fingerprint", "Supply the preflight fingerprint for this review.")
        if action == "bill.post" and (not isinstance(body["periodId"], str) or not body["periodId"] or len(body["periodId"]) > 160
                                      or not isinstance(body["reason"], str) or len(body["reason"]) > 500):
            raise _refusal(422, "invalid_body", "Choose a posting period and a reason of at most 500 characters.")
        binding = {"contractVersion": CONTRACT_VERSION, "fixedAction": action, "resourceId": resource_id,
                   "canonicalTypedBody": dict(body), "originalIfMatch": if_match, "preflightFingerprint": body["fingerprint"]}
        return normalized_key, binding

    def run(self, person_id: str, action: str, resource_id: str, body: dict[str, Any], *,
            repeatability_key: str, if_match: str) -> dict[str, Any]:
        key, binding = self._shape(action, resource_id, body, repeatability_key, if_match)
        deferred: APRefusal | None = None
        response: dict[str, Any] | None = None
        try:
            with self._transaction():
                self.cipher.db.require_practice_mode()
                context = self.preflight.authorize(person_id, action, resource_id)
                canonical_person = context["personId"]
                receipt = self.receipts.find(canonical_person, key)
                if receipt is not None:
                    if receipt["binding_json"] != canonical_json(binding):
                        raise _refusal(409, "repeatability_conflict", "This repeatability key belongs to a different reviewed request.")
                    self._verify_source(receipt)
                    if receipt["outcome"] == "refused":
                        deferred = self._stored_refusal(receipt, replayed=True)
                    else:
                        response = self._response(receipt, replayed=True)
                else:
                    verified = self.preflight.verify(person_id, action, resource_id, body, if_match)
                    if verified.get("personId") != canonical_person or verified.get("login") != context["login"]:
                        raise APIReceiptIntegrityError("Action authority changed during the locked review")
                    if action == "bill.requestApproval":
                        self._refuse_duplicate_request(resource_id, verified)
                    before = self._control_snapshot()
                    try:
                        result, source = self._apply(action, resource_id, body, verified)
                    except (StaleApprovalError, ApprovalExpired) as exc:
                        source = self._terminal_refusal_proof(action, resource_id, verified, before, exc)
                        status = 423 if isinstance(exc, ApprovalExpired) else 412
                        code = "approval_expired" if isinstance(exc, ApprovalExpired) else "approval_stale"
                        result = {"code": code, "message": "The business approval expired. Request a fresh review." if status == 423
                                  else "The business approval changed. Request a fresh review.", "target": source["approvalId"]}
                        receipt = self.receipts.record(person_id=canonical_person, actor_login=context["login"],
                                                       repeatability_uuid=key, contract_version=CONTRACT_VERSION,
                                                       action=action, resource_id=resource_id, binding=binding, outcome="refused",
                                                       http_status=status, result=result, source=source)
                        self._verify_source(receipt)
                        deferred = self._stored_refusal(receipt, replayed=False)
                    else:
                        receipt = self.receipts.record(person_id=canonical_person, actor_login=context["login"],
                                                       repeatability_uuid=key, contract_version=CONTRACT_VERSION,
                                                       action=action, resource_id=resource_id, binding=binding, outcome="success",
                                                       http_status=200, result=result, source=source)
                        self._verify_source(receipt)
                        response = self._response(receipt, replayed=False)
        except APRefusal:
            raise
        except PermissionError:
            raise _refusal(403, "action_not_authorized", "Your current project duties do not permit this action.") from None
        except (ApprovalError, CipherError, BillError):
            raise _refusal(409, "action_refused", "The bill action cannot proceed. Refresh its review and resolve the listed checks.") from None
        except Exception:
            raise _refusal(500, "action_unavailable", "The action did not complete. Retry the same reviewed request.") from None
        # These outcomes leave the transaction normally.  Raising inside it would
        # undo the service's intended stale/expiry bookkeeping and its receipt.
        if deferred is not None:
            raise deferred
        if response is None:
            raise _refusal(500, "action_unavailable", "The action did not complete. Retry the same reviewed request.")
        return response

    def _response(self, receipt: dict[str, Any], *, replayed: bool) -> dict[str, Any]:
        return {"receiptId": receipt["id"], "replayed": replayed, "effectApplied": not replayed,
                "result": loads(receipt["result_json"])}

    def _stored_refusal(self, receipt: dict[str, Any], *, replayed: bool) -> APRefusal:
        value = loads(receipt["result_json"])
        refusal = _refusal(receipt["http_status"], value["code"], value["message"], value["target"])
        refusal.receipt_id = receipt["id"]
        refusal.replayed = replayed
        refusal.effect_applied = False
        return refusal

    def _refuse_duplicate_request(self, bill_id: str, context: dict[str, Any]) -> None:
        current = context.get("manifest") or self.cipher._manifest("bill.approve", bill_id, "pm")
        for ap in self.cipher.approvals.list():
            if (ap["operation"] == "bill.approve" and ap["subject_id"] == bill_id and ap["status"] in ("pending", "granted")
                    and parse_iso(ap["expires_at"]) > utcnow() and material_hash(current) == ap["material_hash"]
                    and current.get("governance") == ap["manifest"].get("governance")):
                self._approval_proof(ap["id"])
                raise _refusal(409, "duplicate_open_approval", "This bill already has a current business approval request.", ap["id"])

    def _apply(self, action: str, resource_id: str, body: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        login, duty = context["login"], context["duty"]
        if action == "bill.requestApproval":
            # Request creation predates the service's grant/post savepoints.  Its
            # own savepoint protects callers that catch a failure in an outer tx.
            conn = self.cipher.db.conn
            savepoint = new_id("ap_request")
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                approval = self.cipher.request_approval("bill.approve", resource_id, actor_role=duty, requested_by=login)
            except BaseException:
                if conn.in_transaction:
                    conn.execute(f"ROLLBACK TO {savepoint}")
                raise
            finally:
                if conn.in_transaction:
                    conn.execute(f"RELEASE {savepoint}")
            proof = self._approval_proof(approval["id"])
            return {"approvalId": approval["id"], "billId": resource_id, "status": "pending"}, {
                "kind": "request", "approvalId": approval["id"], "billId": resource_id, "request": proof}
        if action == "bill.approve":
            self.cipher.approve(resource_id, approver=login, approver_role=duty)
            approval = self.cipher.approvals.get(resource_id)
            bill_id = approval["subject_id"]
            record = self.cipher.db.one("SELECT * FROM bill_business_approvals WHERE approval_id=?", (resource_id,))
            if record is None:
                raise APIReceiptIntegrityError("Business approval has no immutable source record")
            result = {"approvalId": resource_id, "billId": bill_id, "status": "approved",
                      "businessApprovalRecordId": record["id"], "journalDelta": 0, "apDeltaCents": 0}
            return result, {"kind": "grant", "approvalId": resource_id, "billId": bill_id,
                            "recordId": record["id"], "recordHash": record["record_hash"], "request": self._approval_proof(resource_id)}
        self.cipher.post_bill(resource_id, actor=login, actor_role=duty, period_id=body["periodId"], reason=body["reason"])
        receipt = self.cipher.bills.posting_receipt(resource_id)
        if receipt is None:
            raise APIReceiptIntegrityError("Posting has no immutable source receipt")
        result = self._posting_result(receipt)
        return result, {"kind": "post", "billId": resource_id, "approvalId": receipt["approval_id"],
                        "postingReceiptId": receipt["id"], "postingReceiptHash": receipt["receipt_hash"]}

    def _posting_result(self, receipt: dict[str, Any]) -> dict[str, Any]:
        bill = self.cipher.bills.get(receipt["bill_id"])
        return {"billId": receipt["bill_id"], "status": "posted", "journalIds": receipt["journal_ids"],
                "postingReceiptId": receipt["id"], "postingPeriodId": receipt["period_id"],
                "amountDueCents": int(money(bill["amount_due"]) * 100)}

    def _approval_proof(self, approval_id: str) -> dict[str, Any]:
        ap = self.cipher.approvals.get(approval_id)
        manifest = ap["manifest"]
        if (hash_json(manifest) != ap["manifest_hash"] or material_hash(manifest) != ap["material_hash"]
                or ap["operation"] != "bill.approve" or ap["subject_type"] != "bill"
                or manifest.get("subject") != {"type": "bill", "id": ap["subject_id"]}
                or manifest.get("actor_role") != "pm" or ap["actor_role"] != "pm"
                or manifest.get("nonce") != ap["nonce"] or manifest.get("policy_version") != ap["policy_version"]
                or parse_iso(ap["expires_at"]) > parse_iso(manifest["expires_at"])):
            raise APIReceiptIntegrityError("Business approval request differs from its immutable manifest")
        history = self.cipher.db.query("SELECT * FROM audit_log WHERE entity_type='approval' AND entity_id=? ORDER BY seq", (approval_id,))
        requests = [e for e in history if e["action"] == "approval.requested"]
        if len(requests) != 1:
            raise APIReceiptIntegrityError("Business approval requires its original audited request")
        request = requests[0]
        if (request["actor"] != ap["requested_by"] or loads(request["payload_json"]) != {
                "operation": "bill.approve", "subject": manifest["subject"], "manifest_hash": ap["manifest_hash"]}):
            raise APIReceiptIntegrityError("Business approval request differs from its original audit")
        lifecycle = {"approval.requested": "pending", "approval.granted": "granted", "approval.consumed": "consumed",
                     "approval.invalidated": "invalidated", "approval.expired": "expired"}
        changes = [e for e in history if e["action"] in lifecycle]
        if not changes or lifecycle[changes[-1]["action"]] != ap["status"]:
            raise APIReceiptIntegrityError("Business approval lifecycle differs from its audited history")
        for event in changes:
            if event["action"] in ("approval.granted", "approval.consumed"):
                actor = ap["approver"] if event["action"] == "approval.granted" else ap["consumed_by"]
                if event["actor"] != actor or loads(event["payload_json"]) != {"operation": "bill.approve", "material_hash": ap["material_hash"]}:
                    raise APIReceiptIntegrityError("Business approval decision differs from its audit")
        return {"auditSeq": request["seq"], "auditHash": request["entry_hash"], "manifestHash": ap["manifest_hash"],
                "materialHash": ap["material_hash"], "requestedBy": ap["requested_by"], "requestedAt": ap["requested_at"]}

    def _verify_source(self, row: dict[str, Any]) -> None:
        source, result = loads(row["source_json"]), loads(row["result_json"])
        action, resource_id = row["fixed_action"], row["resource_id"]
        actor = self.cipher.plugin("people").person_for(row["actor_login"])
        if actor is None or actor["id"] != row["canonical_person_id"]:
            raise APIReceiptIntegrityError("Action receipt attributes its source to a different canonical person")
        if source["kind"] == "refusal":
            if row["outcome"] != "refused" or action not in ("bill.approve", "bill.post"):
                raise APIReceiptIntegrityError("Refused action has inconsistent source metadata")
            proof = self._approval_proof(source["approvalId"])
            approval = self.cipher.approvals.get(source["approvalId"])
            if proof != source["request"]:
                raise APIReceiptIntegrityError("Refused action no longer matches its original request")
            event = self.cipher.db.one("SELECT * FROM audit_log WHERE seq=?", (source["auditSeq"],))
            if (event is None or event["entry_hash"] != source["auditHash"] or event["action"] != f"approval.{source['status']}"
                    or event["entity_type"] != "approval" or event["entity_id"] != source["approvalId"]
                    or event["actor"] != row["actor_login"] or approval["status"] != source["status"]
                    or resource_id != (source["approvalId"] if action == "bill.approve" else approval["subject_id"])
                    or result.get("target") != source["approvalId"] or row["http_status"] != (423 if source["status"] == "expired" else 412)
                    or result.get("code") != ("approval_expired" if source["status"] == "expired" else "approval_stale")):
                raise APIReceiptIntegrityError("Refused action has no intact terminal control proof")
            return
        if row["outcome"] != "success" or row["http_status"] != 200:
            raise APIReceiptIntegrityError("Successful action has inconsistent receipt metadata")
        if source["kind"] == "request":
            proof = self._approval_proof(source["approvalId"])
            ap = self.cipher.approvals.get(source["approvalId"])
            expected = {"approvalId": source["approvalId"], "billId": resource_id, "status": "pending"}
            if (action != "bill.requestApproval" or source["billId"] != resource_id or ap["subject_id"] != resource_id
                    or ap["requested_by"] != row["actor_login"] or proof != source["request"] or result != expected):
                raise APIReceiptIntegrityError("Request receipt differs from its original approval request")
        elif source["kind"] == "grant":
            proof = self._approval_proof(source["approvalId"])
            ap = self.cipher.approvals.get(source["approvalId"])
            self.cipher.bills._business_history(source["billId"])
            record = self.cipher.db.one("SELECT * FROM bill_business_approvals WHERE id=?", (source["recordId"],))
            expected = {"approvalId": resource_id, "billId": source["billId"], "status": "approved",
                        "businessApprovalRecordId": source["recordId"], "journalDelta": 0, "apDeltaCents": 0}
            if (action != "bill.approve" or source["approvalId"] != resource_id or ap["subject_id"] != source["billId"]
                    or proof != source["request"] or record is None
                    or record["record_hash"] != source["recordHash"] or record["approval_id"] != resource_id
                    or record["bill_id"] != source["billId"] or record["business_hash"] != ap["material_hash"]
                    or record["snapshot_json"] != canonical_json(ap["manifest"]) or record["approved_by"] != row["actor_login"]
                    or record["approved_by"] != ap["approver"] or record["granted_at"] != ap["granted_at"] or result != expected):
                raise APIReceiptIntegrityError("Grant receipt differs from its immutable business decision")
        elif source["kind"] == "post":
            receipt = self.cipher.bills.posting_receipt(source["billId"])
            if (action != "bill.post" or source["billId"] != resource_id or receipt is None
                    or receipt["id"] != source["postingReceiptId"] or receipt["receipt_hash"] != source["postingReceiptHash"]
                    or receipt["approval_id"] != source["approvalId"] or receipt["posted_by"] != row["actor_login"]
                    or self._posting_result(receipt) != result):
                raise APIReceiptIntegrityError("Post receipt differs from its immutable accounting source")
        else:
            raise APIReceiptIntegrityError("Action receipt has an unsupported source proof")

    def _control_snapshot(self) -> dict[str, Any]:
        tables = self.cipher.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        contents = {}
        for table in tables:
            name = table["name"]
            if name in ("approvals", "audit_log"):
                continue
            identifier = '"' + name.replace('"', '""') + '"'
            rows = self.cipher.db.query(f"SELECT * FROM {identifier}")
            contents[name] = hash_json(sorted((canonical_json(r) for r in rows)))
        return {"tables": contents,
                "schema": self.cipher.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"),
                "approvals": self.cipher.db.query("SELECT * FROM approvals ORDER BY id"),
                "audit": self.cipher.db.query("SELECT * FROM audit_log ORDER BY seq")}

    def _terminal_refusal_proof(self, action: str, resource_id: str, context: dict[str, Any], before: dict[str, Any],
                                exc: Exception) -> dict[str, Any]:
        if action not in ("bill.approve", "bill.post"):
            raise APIReceiptIntegrityError("Request failure cannot commit approval control writes")
        approval_id = resource_id if action == "bill.approve" else self.cipher.bills.get(resource_id).get("business_approval_id")
        status = "expired" if isinstance(exc, ApprovalExpired) else "invalidated"
        after = self._control_snapshot()
        old = {r["id"]: r for r in before["approvals"]}
        current = {r["id"]: r for r in after["approvals"]}
        if (before["tables"] != after["tables"] or before["schema"] != after["schema"]
                or old.keys() != current.keys() or approval_id not in old
                or old[approval_id]["status"] not in ("pending", "granted") or current[approval_id]["status"] != status):
            raise APIReceiptIntegrityError("Refusal has unverified partial effects")
        for key in old:
            changed = {column for column in old[key] if old[key][column] != current[key][column]}
            allowed = {"status", "invalidated_reason"} if key == approval_id and status == "invalidated" else {"status"} if key == approval_id else set()
            if not changed <= allowed:
                raise APIReceiptIntegrityError("Refusal changed facts outside its intended control transition")
        previous = before["audit"]
        history = after["audit"]
        if history[:len(previous)] != previous or len(history) != len(previous) + 1:
            raise APIReceiptIntegrityError("Refusal has unexpected audit effects")
        event = history[-1]
        if (event["action"] != f"approval.{status}" or event["entity_type"] != "approval"
                or event["entity_id"] != approval_id or event["actor"] != context["login"]):
            raise APIReceiptIntegrityError("Refusal did not record the intended control transition")
        return {"kind": "refusal", "approvalId": approval_id, "status": status,
                "auditSeq": event["seq"], "auditHash": event["entry_hash"], "request": self._approval_proof(approval_id)}

    def integrity_checks(self) -> list[dict[str, Any]]:
        checks = self.receipts.integrity_checks()
        if not checks[0]["ok"]:
            return checks
        try:
            for row in self.cipher.db.query("SELECT * FROM ap_action_receipts ORDER BY id"):
                self._verify_source(row)
        except Exception:
            return [{"ok": False, "code": "ap_action_sources_integrity", "message": "AP action receipts have inconsistent domain source proof"}]
        return checks + [{"ok": True, "code": "ap_action_sources_integrity", "message": "AP action outcomes match their original domain proof"}]

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        return [{"check": item["code"], "ok": item["ok"], "detail": item["message"]}
                for item in self.integrity_checks()]

    def audit_export(self) -> dict[str, Any]:
        # Local audit export is an owner diagnostic.  HTTP presenters never
        # expose these review bindings or private domain source identifiers.
        return {"integrity": self.integrity_checks(),
                "records": self.cipher.db.query("SELECT * FROM ap_action_receipts ORDER BY created_at,id")}
