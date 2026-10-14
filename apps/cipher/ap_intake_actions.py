"""Six fixed, atomic practice intake actions and their original source proof.

Receipts join the transaction containing the business effect. Current scoped
accountant authority precedes receipt lookup; a completed exact retry verifies
the original audit and immutable records before it returns the original result.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any
from uuid import UUID

from .ap_actions import APActionRunner, CONTRACT_VERSION
from .ap_contract import APRefusal
from .core.api_receipts import APIReceiptIntegrityError
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow
from .core.money import money
from .domain.ap_intake import APIntakeError, OP_MATCH
from .domain.bills import BillError
from .service import CipherError


ACTIONS = frozenset(("bill.prepare", "invoice.receive", "invoice.computeMatch", "invoice.requestMatchApproval",
                     "invoice.approveMatch", "invoice.executeMatch"))
ACTION_TABLES = {
    "bill.prepare": {"bills", "bill_lines", "bill_transfers"},
    "invoice.receive": {"ap_invoices"},
    "invoice.computeMatch": {"ap_invoices", "ap_invoice_matches"},
    "invoice.requestMatchApproval": {"approvals"},
    "invoice.approveMatch": {"approvals"},
    "invoice.executeMatch": {"ap_invoices", "bills", "approvals", "idempotency"},
}
INVOICE_CONTENT_FIELDS = ("id", "version", "project_id", "supplier_id", "commitment_id", "invoice_number", "number_key",
                          "invoice_date", "due_date", "terms_days", "amount", "service_period_start", "service_period_end",
                          "evidence_hash", "evidence_document_id", "evidence_revision_id", "lines_json")


def _cents(value: Any) -> int:
    result = int(money(value) * 100)
    if abs(result) > (1 << 53) - 1:
        raise APIReceiptIntegrityError("A source amount exceeds exact client cents")
    return result


class APIntakeActionRunner(APActionRunner):
    """Fixed intake/preparation routes; no generic module or operation dispatch."""

    def _shape(self, action, resource_id, body, key, if_match):
        if action not in ACTIONS or type(resource_id) is not str or not resource_id or len(resource_id) > 160:
            raise APRefusal(422, "invalid_action", "Choose a supported intake action.", "action")
        try:
            normalized = str(UUID(key)) if type(key) is str and len(key) == 36 else None
        except ValueError:
            normalized = None
        if normalized is None or normalized != key.casefold():
            raise APRefusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.", "Repeatability-Request-ID")
        if type(if_match) is not str or not if_match or len(if_match) > 256:
            raise APRefusal(422, "missing_record_version", "Supply the record version reviewed for this action.", "If-Match")
        typed = self.preflight._body(action, body, action_body=True)
        fingerprint = body.get("fingerprint")
        if type(fingerprint) is not str or not fingerprint or len(fingerprint) > 256:
            raise APRefusal(422, "invalid_fingerprint", "Supply the preflight fingerprint for this review.", "fingerprint")
        binding = {"contractVersion": CONTRACT_VERSION, "fixedAction": action, "resourceId": resource_id,
                   "canonicalTypedBody": {**typed, "fingerprint": fingerprint}, "originalIfMatch": if_match,
                   "preflightFingerprint": fingerprint}
        return normalized, binding

    def run(self, person_id: str, action: str, resource_id: str, body: dict[str, Any], *,
            repeatability_key: str, if_match: str) -> dict[str, Any]:
        key, binding = self._shape(action, resource_id, body, repeatability_key, if_match)
        deferred, response = None, None
        try:
            with self._transaction():
                self.cipher.db.require_practice_mode()
                context = self.preflight.authorize(person_id, action, resource_id)
                canonical_person = context["personId"]
                receipt = self.receipts.find(canonical_person, key)
                if receipt is not None:
                    if receipt["binding_json"] != canonical_json(binding):
                        raise APRefusal(409, "repeatability_conflict", "This repeatability key belongs to a different reviewed request.")
                    self._verify_source(receipt)
                    if receipt["outcome"] == "refused":
                        deferred = self._stored_refusal(receipt, replayed=True)
                    else:
                        response = self._response(receipt, replayed=True)
                else:
                    checked = self.preflight.verify(person_id, action, resource_id, body, if_match)
                    if checked.get("personId") != canonical_person or checked.get("login") != context["login"]:
                        raise APIReceiptIntegrityError("Intake authority changed during the locked review")
                    if action == "invoice.requestMatchApproval":
                        self._refuse_duplicate_request(resource_id, checked)
                    before = self._control_snapshot()
                    try:
                        result, source = self._service_act(action, resource_id, body, checked)
                    except (StaleApprovalError, ApprovalExpired) as exc:
                        source = self._terminal_refusal_proof(action, resource_id, checked, before, exc)
                        status = 423 if isinstance(exc, ApprovalExpired) else 412
                        code = "approval_expired" if status == 423 else "approval_stale"
                        result = {"code": code, "message": "The match authorization expired. Request a fresh review." if status == 423
                                  else "The match facts or authority changed. Request a fresh review.", "target": resource_id}
                        receipt = self.receipts.record(person_id=canonical_person, actor_login=context["login"],
                                                       repeatability_uuid=key, contract_version=CONTRACT_VERSION, action=action,
                                                       resource_id=resource_id, binding=binding, outcome="refused", http_status=status,
                                                       result=result, source=source)
                        self._verify_source(receipt)
                        deferred = self._stored_refusal(receipt, replayed=False)
                    else:
                        receipt = self.receipts.record(person_id=canonical_person, actor_login=context["login"],
                                                       repeatability_uuid=key, contract_version=CONTRACT_VERSION, action=action,
                                                       resource_id=resource_id, binding=binding, outcome="success", http_status=200,
                                                       result=result, source=source)
                        self._verify_source(receipt)
                        response = self._response(receipt, replayed=False)
                    self._verify_effect_boundary(action, resource_id, before, receipt, source)
        except APRefusal:
            raise
        except PermissionError:
            raise APRefusal(403, "action_not_authorized", "Your current project duties do not permit this intake action.") from None
        except (ApprovalError, CipherError, BillError, APIntakeError):
            raise APRefusal(409, "action_refused", "The intake action cannot proceed. Refresh its review and resolve the listed checks.") from None
        except Exception:
            raise APRefusal(500, "action_unavailable", "The intake action did not complete. Retry the same reviewed request.") from None
        if deferred is not None:
            raise deferred
        if response is None:
            raise APRefusal(500, "action_unavailable", "The intake action did not complete. Retry the same reviewed request.")
        return response

    def _service_act(self, action, resource_id, body, context):
        # Generic execute joins an outer transaction. A typed failure can occur
        # after consume or a partial plugin write. Roll the entire service act back
        # first, then record only its intended original approval control transition.
        conn = self.cipher.db.conn
        savepoint = new_id("ap_intake_act")
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            result = self._apply(action, resource_id, body, context)
        except (StaleApprovalError, ApprovalExpired) as exc:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            if action in ("invoice.approveMatch", "invoice.executeMatch"):
                approval = self.cipher.approvals.get(resource_id)
                expected = "pending" if action == "invoice.approveMatch" else "granted"
                if approval["status"] == expected:
                    if isinstance(exc, ApprovalExpired):
                        self.cipher.approvals.mark_expired(resource_id, actor=context["login"])
                    else:
                        self.cipher.approvals.invalidate(resource_id, reason=str(exc), actor=context["login"])
            raise
        except BaseException:
            if conn.in_transaction:
                conn.execute(f"ROLLBACK TO {savepoint}")
                conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            conn.execute(f"RELEASE {savepoint}")
            return result

    def _control_snapshot(self):
        snapshot = super()._control_snapshot()
        tables = set().union(*ACTION_TABLES.values()) | {"ap_action_receipts"}
        snapshot["effectRows"] = {table: self.cipher.db.query(f"SELECT * FROM {table}") for table in tables}
        return snapshot

    @staticmethod
    def _row_effect(before, after, table, *, added=(), changed=None):
        """Require exact inserted IDs and restrict every existing row mutation."""
        key = "op_id" if table == "idempotency" else "id"
        old = {row[key]: row for row in before["effectRows"][table]}
        new = {row[key]: row for row in after["effectRows"][table]}
        if set(old) - set(new) or set(new) - set(old) != set(added):
            raise APIReceiptIntegrityError("An intake action inserted or removed records outside its reviewed resource")
        changed = changed or {}
        for resource_id in old:
            columns = {name for name in old[resource_id] if old[resource_id][name] != new[resource_id][name]}
            if not columns <= changed.get(resource_id, set()):
                raise APIReceiptIntegrityError("An intake action changed facts outside its reviewed resource")
        return old, new

    def _verify_effect_boundary(self, action, resource_id, before, receipt, source):
        """An intake act cannot silently introduce schema or financial effects."""
        after = self._control_snapshot()
        if before["schema"] != after["schema"] or before["tables"].keys() != after["tables"].keys():
            raise APIReceiptIntegrityError("An intake action changed the workspace schema")
        allowed = ACTION_TABLES[action] | {"ap_action_receipts"}
        for table, original in before["tables"].items():
            if table not in allowed and after["tables"][table] != original:
                raise APIReceiptIntegrityError("An intake action changed records outside its fixed effect boundary")
        if "approvals" not in ACTION_TABLES[action] and after["approvals"] != before["approvals"]:
            raise APIReceiptIntegrityError("An intake action changed authorization outside its fixed effect boundary")
        if after["audit"][:len(before["audit"])] != before["audit"]:
            raise APIReceiptIntegrityError("An intake action altered existing audit history")
        additions, changes = {}, {}
        expected_audit = [("ap.practice_action_recorded", "ap_action_receipt", receipt["id"])]
        additions["ap_action_receipts"] = {receipt["id"]}
        if source["kind"] == "refusal":
            changes["approvals"] = {resource_id: {"status", "invalidated_reason"}}
            expected_audit.append((f"approval.{source['status']}", "approval", resource_id))
        elif action == "bill.prepare":
            bill_id = source["billId"]
            additions["bills"] = {bill_id}
            additions["bill_lines"] = {row["id"] for row in source["lines"]}
            # Stored-material certification is excluded by the fixed preflight.
            if source["transfers"]:
                raise APIReceiptIntegrityError("The installed-work API cannot create stored-material transfers")
            expected_audit.append(("bill.certified", "bill", bill_id))
        elif action == "invoice.receive":
            additions["ap_invoices"] = {source["invoiceId"]}
            expected_audit.append(("ap_intake.invoice_received", "ap_invoice", source["invoiceId"]))
        elif action == "invoice.computeMatch":
            additions["ap_invoice_matches"] = {source["attempt"]["row"]["id"]}
            changes["ap_invoices"] = {resource_id: {"version", "content_hash", "status", "match_status", "match_basis",
                                                   "match_exceptions_json", "match_attempt_id", "updated_at"}}
            expected_audit.append(("ap_intake.match_computed", "ap_invoice", resource_id))
            old_invoice = next(row for row in before["effectRows"]["ap_invoices"] if row["id"] == resource_id)
            if source["attempt"]["row"]["invoice_version"] != old_invoice["version"]:
                if source["attempt"]["row"]["invoice_version"] != old_invoice["version"] + 1:
                    raise APIReceiptIntegrityError("The match computation has an unexpected invoice version")
                expected_audit.append(("ap_intake.match_reopened", "ap_invoice", resource_id))
        elif action == "invoice.requestMatchApproval":
            additions["approvals"] = {source["approvalId"]}
            expected_audit.append(("approval.requested", "approval", source["approvalId"]))
        elif action == "invoice.approveMatch":
            changes["approvals"] = {resource_id: {"status", "approver", "granted_at"}}
            expected_audit.append(("approval.granted", "approval", resource_id))
        else:
            invoice_id = source["invoiceId"]
            payload = loads(self._event_row(source["event"])["payload_json"])
            bill_id = payload["bill_id"]
            additions["idempotency"] = {source["commandId"]}
            changes["approvals"] = {resource_id: {"status", "consumed_by", "consumed_at"}}
            changes["ap_invoices"] = {invoice_id: {"status", "match_status", "matched_bill_id", "matched_commitment_id",
                                                   "match_approval_id", "matched_at", "matched_by", "updated_at"}}
            changes["bills"] = {bill_id: {"supplier_invoice_id", "supplier_invoice_number", "invoice_date", "due_date",
                                           "supplier_invoice_hash", "supplier_invoice_evidence_hash", "supplier_invoice_approval_id"}}
            expected_audit.extend((("approval.consumed", "approval", resource_id),
                                   ("ap_intake.invoice_matched", "ap_invoice", invoice_id),
                                   ("bill.supplier_invoice_attached", "bill", bill_id),
                                   ("command.executed", "command", source["commandId"])))
            old_approvals = {row["id"]: row for row in before["approvals"]}
            new_approvals = {row["id"]: row for row in after["approvals"]}
            invoice_invalidations = 0
            for key in old_approvals.keys() & new_approvals.keys():
                previous, current = old_approvals[key], new_approvals[key]
                if key == resource_id or previous == current:
                    continue
                same_invoice = previous["operation"] == OP_MATCH and previous["subject_type"] == "ap_invoice" and previous["subject_id"] == invoice_id
                same_bill = previous["operation"] == "bill.approve" and previous["subject_type"] == "bill" and previous["subject_id"] == bill_id
                if (not (same_invoice or same_bill) or previous["status"] not in ("pending", "granted")
                        or current["status"] != "invalidated"):
                    raise APIReceiptIntegrityError("Match execution changed an unrelated authorization")
                invoice_invalidations += int(same_invoice)
                changes["approvals"][key] = {"status", "invalidated_reason"}
                expected_audit.append(("approval.invalidated", "approval", key))
            if invoice_invalidations != payload["approvals_invalidated"]:
                raise APIReceiptIntegrityError("Match execution has inconsistent intended authorization invalidations")
        for table in before["effectRows"]:
            self._row_effect(before, after, table, added=additions.get(table, ()), changed=changes.get(table))
        actual = after["audit"][len(before["audit"]):]
        if (Counter((event["action"], event["entity_type"], event["entity_id"]) for event in actual) != Counter(expected_audit)
                or any(event["actor"] != receipt["actor_login"] for event in actual)):
            raise APIReceiptIntegrityError("An intake action appended an unreviewed audit effect")

    def _refuse_duplicate_request(self, invoice_id, context):
        current = context.get("manifest") or self.cipher._manifest(OP_MATCH, invoice_id, "accountant")
        for approval in self.cipher.approvals.list():
            if (approval["operation"] == OP_MATCH and approval["subject_id"] == invoice_id
                    and approval["status"] in ("pending", "granted") and parse_iso(approval["expires_at"]) > utcnow()
                    and material_hash(current) == approval["material_hash"]
                    and current.get("governance") == approval["manifest"].get("governance")):
                self._approval_proof(approval["id"])
                raise APRefusal(409, "duplicate_open_approval", "This invoice already has a current match approval request.", approval["id"])

    def _evidence(self, revision_id, project_id):
        row = self.cipher.db.one("""SELECT r.*,d.project_id,d.kind FROM document_revisions r
            JOIN documents d ON d.id=r.document_id WHERE r.id=? AND d.project_id=? AND d.kind='supplier_invoice'""",
                                 (revision_id, project_id))
        if row is None:
            raise APRefusal(404, "not_found", "The invoice evidence is unavailable in this practice session.", "evidenceRevisionId")
        return row

    def _apply(self, action, resource_id, body, context):
        c, login, intake = self.cipher, context["login"], self.cipher.plugin("ap_intake")
        typed = self.preflight._body(action, body, action_body=True)
        if action == "bill.prepare":
            params = {"commitment_id": resource_id, "period_id": typed["periodId"],
                      "installed": [{"sov_line_id": item["sovLineId"], "cumulative_installed": Decimal(item["cumulativeInstalledCents"]) / 100}
                                    for item in typed["installed"]]}
            plan = c.bills.certification_preflight(**params)
            bill = c.bills.certify(**params, actor=login)
            source = {"kind": "prepare", "billId": bill["id"], "content": plan["content"],
                      "header": c.bills._immutable_bill_facts(bill), "lines": self._bill_lines(bill["id"]),
                      "transfers": bill["transfers"], "event": self._event("bill.certified", "bill", bill["id"])}
            return {"billId": bill["id"], "commitmentId": resource_id, "status": "draft", "sequence": bill["sequence"],
                    "amountDueCents": _cents(bill["amount_due"]), "retainageCents": _cents(bill["retainage_this_period"]),
                    "journalDelta": 0, "apDeltaCents": 0}, source
        if action == "invoice.receive":
            commitment = c.commitments.get(resource_id)
            evidence = self._evidence(typed["evidenceRevisionId"], context["projectId"])
            inv = intake.receive_invoice(commitment["supplier_id"], typed["invoiceNumber"], typed["invoiceDate"],
                                         Decimal(typed["amountCents"]) / 100, evidence["content_hash"], login,
                                         project_id=context["projectId"], commitment_id=resource_id)
            stored = intake._row(inv["id"])
            source = {"kind": "receive", "invoiceId": inv["id"], "original": {k: stored[k] for k in INVOICE_CONTENT_FIELDS},
                      "contentHash": stored["content_hash"], "createdAt": stored["created_at"],
                      "event": self._event("ap_intake.invoice_received", "ap_invoice", inv["id"])}
            return {"invoiceId": inv["id"], "commitmentId": resource_id, "status": "received", "invoiceNumber": inv["invoice_number"],
                    "amountCents": _cents(inv["amount"]), "dueDate": inv["due_date"], "possibleDuplicate": bool(inv["possible_duplicate"]),
                    "journalDelta": 0, "apDeltaCents": 0}, source
        if action == "invoice.computeMatch":
            computed = intake.match(resource_id, login)
            attempt = self._attempt_source(computed["attempt_id"])
            return self._computation_result(attempt["row"]), {"kind": "compute", "invoiceId": resource_id, "attempt": attempt}
        if action == "invoice.requestMatchApproval":
            approval = c.request_approval(OP_MATCH, resource_id, actor_role="accountant", requested_by=login)
            return {"approvalId": approval["id"], "invoiceId": resource_id, "status": "pending", "journalDelta": 0, "apDeltaCents": 0}, {
                "kind": "matchRequest", "approvalId": approval["id"], "invoiceId": resource_id,
                "request": self._approval_proof(approval["id"])}
        if action == "invoice.approveMatch":
            c.approve(resource_id, approver=login, approver_role="accountant")
            approval = c.approvals.get(resource_id)
            return {"approvalId": resource_id, "invoiceId": approval["subject_id"], "status": "granted", "journalDelta": 0, "apDeltaCents": 0}, {
                "kind": "matchGrant", "approvalId": resource_id, "invoiceId": approval["subject_id"],
                "request": self._approval_proof(resource_id), "event": self._event("approval.granted", "approval", resource_id)}
        c.check_invoice_match_execution(resource_id, actor=login)
        executed = c.execute(resource_id, actor=login)
        approval = c.approvals.get(resource_id)
        invoice_id = approval["subject_id"]
        event = self._event("ap_intake.invoice_matched", "ap_invoice", invoice_id, approval_id=resource_id)
        matched = loads(self._event_row(event)["payload_json"])
        if matched["basis"] != "progress" or not matched["bill_id"]:
            raise APIReceiptIntegrityError("The fixed intake workflow requires a certified progress bill")
        source = {"kind": "matchExecute", "approvalId": resource_id, "invoiceId": invoice_id,
                  "request": self._approval_proof(resource_id), "event": event,
                  "attachment": self._event("bill.supplier_invoice_attached", "bill", matched["bill_id"], approval_id=resource_id),
                  "attempt": self._attempt_source(matched["attempt_id"]), "commandId": executed.op_id}
        return {"approvalId": resource_id, "invoiceId": invoice_id, "billId": matched["bill_id"], "status": "matched",
                "amountCents": _cents(matched["amount"]), "dueDate": matched["due_date"], "journalDelta": 0, "apDeltaCents": 0}, source

    def _approval_proof(self, approval_id):
        from .ap_intake_preflight import approval_proof
        proof = approval_proof(self.cipher, approval_id)
        if self.cipher.approvals.get(approval_id)["actor_role"] != "accountant":
            raise APIReceiptIntegrityError("The fixed intake API uses an accountant match authorization")
        return proof

    def _event(self, action, entity_type, entity_id, *, approval_id=None):
        rows = self.cipher.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type=? AND entity_id=? ORDER BY seq",
                                    (action, entity_type, entity_id))
        if approval_id is not None:
            rows = [r for r in rows if loads(r["payload_json"]).get("approval_id") == approval_id]
        if len(rows) != 1:
            raise APIReceiptIntegrityError("An intake action requires its unique original audit event")
        return {"seq": rows[0]["seq"], "hash": rows[0]["entry_hash"]}

    def _event_row(self, proof):
        row = self.cipher.db.one("SELECT * FROM audit_log WHERE seq=?", (proof["seq"],))
        if row is None or row["entry_hash"] != proof["hash"]:
            raise APIReceiptIntegrityError("An intake source event differs from its original audit")
        return row

    def _bill_lines(self, bill_id):
        return self.cipher.db.query("SELECT * FROM bill_lines WHERE bill_id=? ORDER BY id", (bill_id,))

    def _verify_invoice_current(self, invoice_id):
        try:
            return self.cipher.plugin("ap_intake").invoice_proof(invoice_id)
        except (APIntakeError, ApprovalError) as exc:
            raise APIReceiptIntegrityError("The invoice's current lifecycle or original source cannot be verified") from exc

    def _attempt_source(self, attempt_id):
        row = self.cipher.db.one("SELECT * FROM ap_invoice_matches WHERE id=?", (attempt_id,))
        if row is None:
            raise APIReceiptIntegrityError("The original match computation is missing")
        events = self.cipher.db.query("SELECT * FROM audit_log WHERE action='ap_intake.match_computed' AND entity_type='ap_invoice' AND entity_id=? ORDER BY seq",
                                    (row["invoice_id"],))
        events = [e for e in events if loads(e["payload_json"]).get("attempt_id") == attempt_id]
        facts = loads(row["result_json"])
        if len(events) != 1:
            raise APIReceiptIntegrityError("The original match computation requires its unique audit event")
        event = events[0]
        payload = loads(event["payload_json"])
        if (row["result_json"] != canonical_json(facts) or row["result_hash"] != hash_json(facts)
                or facts["invoice"]["id"] != row["invoice_id"] or facts["invoice"]["version"] != row["invoice_version"]
                or row["exceptions_json"] != canonical_json(facts["exceptions"])
                or row["basis"] != facts["basis"] or row["status"] != facts["status"]
                or event["actor"] != row["computed_by"] or payload.get("invoice_version") != row["invoice_version"]
                or payload.get("result_hash") != row["result_hash"] or payload.get("basis") != row["basis"]
                or payload.get("status") != row["status"] or payload.get("exceptions") != facts["exceptions"]
                or payload.get("bill_id") != (facts.get("bill") or {}).get("id")
                or payload.get("receipts") != [r["receipt_id"] for r in facts["receipts"]]):
            raise APIReceiptIntegrityError("The computation differs from its original audited facts")
        self._verify_invoice_current(row["invoice_id"])
        return {"row": row, "event": {"seq": event["seq"], "hash": event["entry_hash"]}}

    def _computation_result(self, row):
        facts = loads(row["result_json"])
        result = {"invoiceId": row["invoice_id"], "attemptId": row["id"], "invoiceVersion": row["invoice_version"],
                "status": row["status"], "basis": row["basis"], "exceptions": facts["exceptions"],
                "billId": (facts.get("bill") or {}).get("id"),
                "journalDelta": 0, "apDeltaCents": 0}
        if facts["matched_amount"] is not None:
            result["matchedAmountCents"] = _cents(facts["matched_amount"])
        return result

    def _verify_source(self, row):
        action, resource = row["fixed_action"], row["resource_id"]
        if action not in ACTIONS:
            raise APIReceiptIntegrityError("An intake receipt has an unsupported action")
        source, result = loads(row["source_json"]), loads(row["result_json"])
        binding = loads(row["binding_json"])
        try:
            _key, expected_binding = self._shape(action, resource, binding["canonicalTypedBody"], row["repeatability_uuid"], binding["originalIfMatch"])
        except (APRefusal, KeyError, TypeError, ValueError) as exc:
            raise APIReceiptIntegrityError("An intake receipt has an invalid original review binding") from exc
        if binding != expected_binding or row["contract_version"] != CONTRACT_VERSION:
            raise APIReceiptIntegrityError("An intake receipt has inconsistent original review metadata")
        typed = self.preflight._body(action, binding["canonicalTypedBody"], action_body=True)
        actor = self.cipher.plugin("people").person_for(row["actor_login"])
        if actor is None or actor["id"] != row["canonical_person_id"]:
            raise APIReceiptIntegrityError("The receipt attributes its source to a different canonical person")
        if source["kind"] == "refusal":
            return self._verify_refusal(row, source, result)
        if row["outcome"] != "success" or row["http_status"] != 200:
            raise APIReceiptIntegrityError("A successful intake action has inconsistent metadata")
        if source["kind"] == "prepare":
            bill = self.cipher.bills.get(source["billId"])
            try:
                self.contract.base._verify_bill(bill)
            except APRefusal as exc:
                raise APIReceiptIntegrityError("The prepared bill's current lifecycle or source cannot be verified") from exc
            content = source["content"]
            event = self._event_row(source["event"])
            payload = loads(event["payload_json"])
            if (action != "bill.prepare" or bill["commitment_id"] != resource or content["commitment_id"] != resource
                    or event["action"] != "bill.certified" or event["entity_type"] != "bill" or event["entity_id"] != bill["id"]
                    or event["actor"] != row["actor_login"] or payload.get("content_hash") != hash_json(content)
                    or bill["content_hash"] != hash_json(content) or self.cipher.bills._immutable_bill_facts(bill) != source["header"]
                    or self._bill_lines(bill["id"]) != source["lines"] or bill["transfers"] != source["transfers"]
                    or any(bill[key] != content[key] for key in ("period_id", "sequence", "commitment_version", "amount_due", "cumulative_installed",
                                                              "cumulative_stored", "cumulative_gross", "cumulative_retainage", "cumulative_net", "prior_net", "sov_hash", "retainage_rate"))):
                raise APIReceiptIntegrityError("Prepared bill proof differs from its original certification")
            quantities = {line["sov_line_id"]: _cents(line["cumulative_installed"]) for line in content["lines"]}
            if (typed["periodId"] != content["period_id"]
                    or any(quantities.get(line["sovLineId"]) != line["cumulativeInstalledCents"] for line in typed["installed"])):
                raise APIReceiptIntegrityError("The prepared quantities differ from the original typed review")
            expected = {"billId": bill["id"], "commitmentId": resource, "status": "draft", "sequence": bill["sequence"],
                        "amountDueCents": _cents(bill["amount_due"]), "retainageCents": _cents(bill["retainage_this_period"]),
                        "journalDelta": 0, "apDeltaCents": 0}
        elif source["kind"] == "receive":
            intake = self.cipher.plugin("ap_intake")
            current = self._verify_invoice_current(source["invoiceId"])
            original = source["original"]
            event = self._event_row(source["event"])
            payload = loads(event["payload_json"])
            if (action != "invoice.receive" or original["id"] != source["invoiceId"] or original["version"] != 1
                    or original["commitment_id"] != resource or current["created_at"] != source["createdAt"]
                    or intake._content_hash(original) != source["contentHash"] or payload.get("content_hash") != source["contentHash"]
                    or event["action"] != "ap_intake.invoice_received" or event["entity_type"] != "ap_invoice"
                    or event["entity_id"] != original["id"] or event["actor"] != row["actor_login"]
                    or any(payload.get(field) != original[field] for field in ("project_id", "supplier_id", "commitment_id", "invoice_number", "number_key", "invoice_date", "due_date", "terms_days", "amount", "evidence_hash", "evidence_revision_id"))
                    or payload.get("lines") != len(loads(original["lines_json"]))):
                raise APIReceiptIntegrityError("Received invoice proof differs from its original source facts")
            if (typed["invoiceNumber"] != original["invoice_number"] or typed["invoiceDate"] != original["invoice_date"]
                    or typed["amountCents"] != _cents(original["amount"]) or typed["evidenceRevisionId"] != original["evidence_revision_id"]):
                raise APIReceiptIntegrityError("The received invoice differs from the original typed review")
            expected = {"invoiceId": original["id"], "commitmentId": resource, "status": "received", "invoiceNumber": original["invoice_number"],
                        "amountCents": _cents(original["amount"]), "dueDate": original["due_date"],
                        "possibleDuplicate": bool(payload["possible_duplicate"]), "journalDelta": 0, "apDeltaCents": 0}
        elif source["kind"] == "compute":
            attempt = self._attempt_source(source["attempt"]["row"]["id"])
            if (action != "invoice.computeMatch" or source["invoiceId"] != resource or attempt != source["attempt"]
                    or attempt["row"]["invoice_id"] != resource or attempt["row"]["computed_by"] != row["actor_login"]):
                raise APIReceiptIntegrityError("Match computation receipt differs from its immutable attempt")
            expected = self._computation_result(attempt["row"])
        elif source["kind"] in ("matchRequest", "matchGrant", "matchExecute"):
            approval = self.cipher.approvals.get(source["approvalId"])
            if (self._approval_proof(approval["id"]) != source["request"] or approval["subject_id"] != source["invoiceId"]):
                raise APIReceiptIntegrityError("The intake decision no longer matches its original approval request")
            self._verify_invoice_current(source["invoiceId"])
            expected = self._decision_result(row, source, approval)
        else:
            raise APIReceiptIntegrityError("An intake receipt has an unsupported source proof")
        if result != expected:
            raise APIReceiptIntegrityError("An intake result differs from its original domain outcome")

    def _decision_result(self, row, source, approval):
        action, resource, login = row["fixed_action"], row["resource_id"], row["actor_login"]
        if source["kind"] == "matchRequest":
            if action != "invoice.requestMatchApproval" or resource != source["invoiceId"] or approval["requested_by"] != login:
                raise APIReceiptIntegrityError("Match request has inconsistent origin")
            return {"approvalId": approval["id"], "invoiceId": resource, "status": "pending", "journalDelta": 0, "apDeltaCents": 0}
        event = self._event_row(source["event"])
        if source["kind"] == "matchGrant":
            if (action != "invoice.approveMatch" or resource != approval["id"] or approval["approver"] != login
                    or event["action"] != "approval.granted" or event["entity_type"] != "approval" or event["entity_id"] != resource
                    or event["actor"] != login or loads(event["payload_json"]) != {"operation": OP_MATCH, "material_hash": approval["material_hash"]}):
                raise APIReceiptIntegrityError("Match grant has no original human decision proof")
            return {"approvalId": resource, "invoiceId": source["invoiceId"], "status": "granted", "journalDelta": 0, "apDeltaCents": 0}
        payload = loads(event["payload_json"])
        attempt = self._attempt_source(source["attempt"]["row"]["id"])
        attachment = self._event_row(source["attachment"])
        linked = loads(attachment["payload_json"])
        bound = approval["manifest"]["bindings"]
        bill = bound["bill"]
        if (action != "invoice.executeMatch" or resource != approval["id"] or approval["status"] != "consumed" or approval["consumed_by"] != login
                or event["action"] != "ap_intake.invoice_matched" or event["entity_type"] != "ap_invoice" or event["entity_id"] != source["invoiceId"]
                or event["actor"] != login or payload.get("approval_id") != resource or payload.get("basis") != "progress"
                or payload.get("invoice_version") != bound["invoice_version"] or payload.get("attempt_id") != bound["match_attempt_id"]
                or payload.get("bill_id") != bill["id"] or payload.get("amount") != approval["manifest"]["amounts"]["invoice_amount"]
                or payload.get("due_date") != bound["due_date"] or attempt != source["attempt"]
                or attachment["action"] != "bill.supplier_invoice_attached" or attachment["entity_type"] != "bill" or attachment["entity_id"] != bill["id"]
                or attachment["actor"] != login or linked.get("approval_id") != resource or linked.get("supplier_invoice_id") != source["invoiceId"]
                or linked.get("supplier_invoice_hash") != bound["invoice_hash"] or linked.get("supplier_invoice_evidence_hash") != bound["evidence_hash"]
                or linked.get("amount_due") != bill["amount_due"]):
            raise APIReceiptIntegrityError("Match execution no longer agrees with its original consumed approval and attachment")
        command = self.cipher.db.one("SELECT * FROM idempotency WHERE op_id=?", (source["commandId"],))
        command_payload = {"approval_id": resource, "operation": OP_MATCH, "subject_id": source["invoiceId"]}
        command_result = {"invoice": source["invoiceId"], "status": "matched", "basis": "progress", "bill": bill["id"],
                          "receipts": payload["receipts"], "amount": payload["amount"], "due_date": payload["due_date"]}
        command_events = self.cipher.db.query("SELECT * FROM audit_log WHERE action='command.executed' AND entity_type='command' AND entity_id=?",
                                              (source["commandId"],))
        if (source["commandId"] != f"exec:{resource}" or command is None or command["payload_hash"] != hash_json(command_payload)
                or command["result_json"] != canonical_json(command_result) or len(command_events) != 1
                or command_events[0]["actor"] != login or loads(command_events[0]["payload_json"]) != {"payload_hash": hash_json(command_payload)}):
            raise APIReceiptIntegrityError("Match execution has inconsistent original command proof")
        return {"approvalId": resource, "invoiceId": source["invoiceId"], "billId": bill["id"], "status": "matched",
                "amountCents": _cents(payload["amount"]), "dueDate": payload["due_date"], "journalDelta": 0, "apDeltaCents": 0}

    def _terminal_refusal_proof(self, action, resource_id, context, before, exc):
        if action not in ("invoice.approveMatch", "invoice.executeMatch"):
            raise APIReceiptIntegrityError("Preparation failure cannot commit approval control writes")
        status = "expired" if isinstance(exc, ApprovalExpired) else "invalidated"
        after = self._control_snapshot()
        old = {r["id"]: r for r in before["approvals"]}
        current = {r["id"]: r for r in after["approvals"]}
        expected = "pending" if action == "invoice.approveMatch" else "granted"
        if (before["tables"] != after["tables"] or before["schema"] != after["schema"] or old.keys() != current.keys()
                or resource_id not in old or old[resource_id]["status"] != expected or current[resource_id]["status"] != status):
            raise APIReceiptIntegrityError("Match refusal has unverified partial effects")
        for key in old:
            changed = {column for column in old[key] if old[key][column] != current[key][column]}
            allowed = {"status", "invalidated_reason"} if key == resource_id and status == "invalidated" else {"status"} if key == resource_id else set()
            if not changed <= allowed:
                raise APIReceiptIntegrityError("Match refusal changed facts outside its intended control transition")
        previous, history = before["audit"], after["audit"]
        if history[:len(previous)] != previous or len(history) != len(previous) + 1:
            raise APIReceiptIntegrityError("Match refusal has unexpected audit effects")
        event = history[-1]
        if (event["action"] != f"approval.{status}" or event["entity_type"] != "approval" or event["entity_id"] != resource_id
                or event["actor"] != context["login"]):
            raise APIReceiptIntegrityError("Match refusal did not record the intended original control transition")
        return {"kind": "refusal", "approvalId": resource_id, "status": status,
                "event": {"seq": event["seq"], "hash": event["entry_hash"]}, "request": self._approval_proof(resource_id)}

    def _verify_refusal(self, row, source, result):
        action, resource = row["fixed_action"], row["resource_id"]
        event = self._event_row(source["event"])
        approval = self.cipher.approvals.get(source["approvalId"])
        status = source["status"]
        if (action not in ("invoice.approveMatch", "invoice.executeMatch") or row["outcome"] != "refused" or resource != source["approvalId"]
                or self._approval_proof(resource) != source["request"] or approval["status"] != status or status not in ("expired", "invalidated")
                or event["action"] != f"approval.{status}" or event["entity_type"] != "approval" or event["entity_id"] != resource
                or event["actor"] != row["actor_login"] or result.get("target") != resource
                or row["http_status"] != (423 if status == "expired" else 412)
                or result.get("code") != ("approval_expired" if status == "expired" else "approval_stale")):
            raise APIReceiptIntegrityError("Match refusal has no intact original terminal control proof")

    def integrity_checks(self):
        checks = self.receipts.integrity_checks()
        if not checks[0]["ok"]:
            return checks
        try:
            for row in self._records():
                self._verify_source(row)
        except Exception:
            return [{"ok": False, "code": "ap_intake_action_sources_integrity", "message": "Intake action receipts have inconsistent original domain proof"}]
        return checks + [{"ok": True, "code": "ap_intake_action_sources_integrity", "message": "Intake outcomes match their original audited domain proof"}]

    def _records(self):
        return self.cipher.db.query("SELECT * FROM ap_action_receipts WHERE fixed_action IN (?,?,?,?,?,?) ORDER BY created_at,id", tuple(sorted(ACTIONS)))

    def audit_export(self):
        return {"integrity": self.integrity_checks(), "records": self._records()}
