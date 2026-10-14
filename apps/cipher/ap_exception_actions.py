"""Atomic fixed AP exception and posted-bill correction practice actions."""
from __future__ import annotations

from collections import Counter
import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from .ap_actions import APActionRunner, CONTRACT_VERSION
from .ap_contract import APRefusal
from .ap_intake_actions import APIntakeActionRunner, INVOICE_CONTENT_FIELDS, _cents
from .core.api_receipts import APIReceiptIntegrityError, APIRepeatabilityConflict
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow
from .domain.ap_intake import APIntakeError
from .domain.bills import BillError
from .domain.ledger import lines_fingerprint
from .service import CipherError


ACTIONS = frozenset(("invoice.revise", "invoice.reject", "invoice.reviewDuplicate", "bill.cancel", "bill.prepareCorrection",
                     "bill.requestCorrection", "bill.approveCorrection", "bill.executeCorrection"))
TABLES = {
    "invoice.revise": {"ap_invoices", "approvals"}, "invoice.reject": {"ap_invoices", "approvals"},
    "invoice.reviewDuplicate": {"ap_invoices"}, "bill.cancel": {"bills", "approvals"},
    "bill.prepareCorrection": {"bill_corrections"}, "bill.requestCorrection": {"approvals"},
    "bill.approveCorrection": {"approvals"},
    "bill.executeCorrection": {"bills", "bill_corrections", "approvals", "journals", "journal_lines", "journal_reversal_requests", "idempotency"},
}


class APExceptionActionRunner(APIntakeActionRunner):
    def _shape(self, action, resource_id, body, key, if_match):
        if action not in ACTIONS or type(resource_id) is not str or not resource_id or len(resource_id) > 160:
            raise APRefusal(422, "invalid_action", "Choose a supported AP exception action.", "action")
        try:
            normalized = str(UUID(key)) if type(key) is str and len(key) == 36 else None
        except ValueError:
            normalized = None
        if normalized is None or normalized != key.casefold():
            raise APRefusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.")
        if type(if_match) is not str or not if_match or len(if_match) > 256:
            raise APRefusal(422, "missing_record_version", "Supply the record version reviewed for this action.")
        typed = self.preflight._body(action, body, action_body=True)
        fingerprint = body.get("fingerprint")
        if type(fingerprint) is not str or not fingerprint or len(fingerprint) > 256:
            raise APRefusal(422, "invalid_fingerprint", "Supply the preflight fingerprint for this review.")
        return normalized, {"contractVersion": CONTRACT_VERSION, "fixedAction": action, "resourceId": resource_id,
                            "canonicalTypedBody": {**typed, "fingerprint": fingerprint}, "originalIfMatch": if_match,
                            "preflightFingerprint": fingerprint}

    def run(self, person_id, action, resource_id, body, *, repeatability_key, if_match):
        key, binding = self._shape(action, resource_id, body, repeatability_key, if_match)
        deferred, response = None, None
        try:
            with self._transaction():
                self.cipher.db.require_practice_mode()
                context = self.preflight.authorize(person_id, action, resource_id)
                person = context["personId"]
                self.receipts.require_repeatability_namespace(person, key, action, binding)
                receipt = self.receipts.find(person, key)
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
                    if checked.get("personId") != person or checked.get("login") != context["login"]:
                        raise APIReceiptIntegrityError("Exception authority changed during the locked review")
                    if action == "bill.requestCorrection":
                        self._refuse_duplicate_request(resource_id, checked)
                    before = self._control_snapshot()
                    reviewed_plan = loads(canonical_json(checked.get("plan")))
                    try:
                        result, source = self._service_act(action, resource_id, body, checked)
                    except (StaleApprovalError, ApprovalExpired) as exc:
                        source = self._terminal_refusal_proof(action, resource_id, checked, before, exc)
                        status = 423 if isinstance(exc, ApprovalExpired) else 412
                        result = {"code": "approval_expired" if status == 423 else "approval_stale",
                                  "message": "The correction authorization expired. Request a fresh review." if status == 423
                                  else "The correction facts or authority changed. Request a fresh review.", "target": resource_id}
                        receipt = self.receipts.record(person_id=person, actor_login=context["login"], repeatability_uuid=key,
                            contract_version=CONTRACT_VERSION, action=action, resource_id=resource_id, binding=binding,
                            outcome="refused", http_status=status, result=result, source=source)
                        self._verify_source(receipt)
                        deferred = self._stored_refusal(receipt, replayed=False)
                    else:
                        self._verify_reviewed_plan(action, resource_id, reviewed_plan, checked, source, before)
                        receipt = self.receipts.record(person_id=person, actor_login=context["login"], repeatability_uuid=key,
                            contract_version=CONTRACT_VERSION, action=action, resource_id=resource_id, binding=binding,
                            outcome="success", http_status=200, result=result, source=source)
                        self._verify_source(receipt)
                        response = self._response(receipt, replayed=False)
                    self._verify_effect_boundary(action, resource_id, before, receipt, source)
        except APRefusal:
            raise
        except APIRepeatabilityConflict:
            raise APRefusal(409, "repeatability_conflict", "This key belongs to a different original reviewed request.") from None
        except PermissionError:
            raise APRefusal(403, "action_not_authorized", "Your current project duties do not permit this exception action.") from None
        except (ApprovalError, CipherError, BillError, APIntakeError):
            raise APRefusal(409, "action_refused", "The exception action cannot proceed. Refresh its review and resolve the listed checks.") from None
        except Exception:
            raise APRefusal(500, "action_unavailable", "The exception action did not complete. Retry the same reviewed request.") from None
        if deferred is not None:
            raise deferred
        if response is None:
            raise APRefusal(500, "action_unavailable", "The exception action did not complete. Retry the same reviewed request.")
        return response

    def _service_act(self, action, resource_id, body, context):
        conn = self.cipher.db.conn
        name = new_id("exception_act")
        conn.execute(f"SAVEPOINT {name}")
        try:
            result = self._apply(action, resource_id, body, context)
        except (StaleApprovalError, ApprovalExpired) as exc:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            if action in ("bill.approveCorrection", "bill.executeCorrection"):
                approval = self.cipher.approvals.get(resource_id)
                expected = "pending" if action == "bill.approveCorrection" else "granted"
                if approval["status"] == expected:
                    if isinstance(exc, ApprovalExpired):
                        self.cipher.approvals.mark_expired(resource_id, actor=context["login"])
                    else:
                        self.cipher.approvals.invalidate(resource_id, reason=str(exc), actor=context["login"])
            raise
        except BaseException:
            if conn.in_transaction:
                conn.execute(f"ROLLBACK TO {name}")
                conn.execute(f"RELEASE {name}")
            raise
        else:
            conn.execute(f"RELEASE {name}")
            return result

    def _control_snapshot(self):
        snapshot = APActionRunner._control_snapshot(self)
        tables = set().union(*TABLES.values()) | {"ap_action_receipts"}
        snapshot["effectRows"] = {table: self.cipher.db.query(f"SELECT * FROM {table}") for table in tables}
        return snapshot

    def _verify_reviewed_plan(self, action, resource_id, plan, context, source, before):
        if action.startswith("invoice."):
            actual = self.cipher.plugin("ap_intake")._row(resource_id)
            expected = dict(plan["content"])
            if action == "invoice.revise":
                review = plan["duplicate_review"]
                expected.update(status=plan["invoice_status"], possible_duplicate=int(plan["possible_duplicate"]),
                    duplicate_of_json=canonical_json(plan["possible_duplicate_of"]), duplicate_cleared_by=review["cleared_by"],
                    duplicate_cleared_at=review["cleared_at"], duplicate_clear_reason=review["reason"],
                    match_status=None, match_basis=None, match_attempt_id=None, match_exceptions_json="[]")
                # Every unrelated source/lifecycle field retains its reviewed value.
                expected = {**plan["source_facts"]["invoice"], **expected}
            elif action == "invoice.reject":
                event = loads(self._event_row(source["event"])["payload_json"])
                expected.update(status=plan["invoice_status"], rejected_by=context["login"], rejected_at=event["rejected_at"], reject_reason=plan["reason"])
            else:
                event = loads(self._event_row(source["event"])["payload_json"])
                expected.update(duplicate_cleared_by=context["login"], duplicate_cleared_at=event["cleared_at"], duplicate_clear_reason=plan["reason"])
            expected.pop("updated_at", None)
            if any(actual.get(key) != value for key, value in expected.items()):
                raise APIReceiptIntegrityError("The invoice exception differs from its complete reviewed content and control plan")
            self._verify_intended_invalidations(plan["invalidated_approval_ids"], before)
        elif action == "bill.cancel":
            self._verify_intended_invalidations(plan["open_approval_ids"], before)
        elif action == "bill.prepareCorrection":
            request = self.cipher.bills.correction_proof(source["correctionId"])
            if (request["bill_id"] != plan["facts"]["bill"]["id"] or request["reason"] != plan["reason"]
                    or request["status"] != "pending" or request["requested_by"] != context["login"]):
                raise APIReceiptIntegrityError("The correction preparation differs from its complete reviewed subject and reason")
        elif action == "bill.executeCorrection":
            bill_id = source["billId"]
            intended = [row["id"] for row in before["approvals"] if row["subject_type"] == "bill" and row["subject_id"] == bill_id
                        and row["status"] in ("pending", "granted") and row["id"] != resource_id]
            self._verify_intended_invalidations(intended, before, consumed=resource_id)
            if len(source["journals"]) != len(plan["journal_preview"]):
                raise APIReceiptIntegrityError("The reversal inventory differs from its complete reviewed plan")
            for actual, expected in zip(source["journals"], plan["journal_preview"]):
                if any(actual["row"].get(key) != value for key, value in expected.items() if key != "lines"):
                    raise APIReceiptIntegrityError("The reversal source differs from its complete reviewed journal plan")
                lines = [{"account": line["account_code"], **{key: line[key] for key in ("debit", "credit", "project_id", "party_id", "memo")}}
                         for line in actual["lines"]]
                if lines != expected["lines"]:
                    raise APIReceiptIntegrityError("The reversal entries differ from the complete reviewed journal plan")
        elif action == "bill.requestCorrection":
            approval = self.cipher.approvals.get(source["approvalId"])
            if (material_hash(context["manifest"]) != approval["material_hash"]
                    or context["manifest"].get("governance") != approval["manifest"].get("governance")):
                raise APIReceiptIntegrityError("The requested correction authorization differs from its complete reviewed manifest")

    def _verify_intended_invalidations(self, approval_ids, before, *, consumed=None):
        intended = set(approval_ids)
        current = {row["id"]: row for row in self.cipher.db.query("SELECT * FROM approvals")}
        changed = {row["id"] for row in before["approvals"] if row != current.get(row["id"]) and row["id"] != consumed}
        if (changed != intended or any(current[key]["status"] != "invalidated" for key in intended)
                or consumed is not None and current[consumed]["status"] != "consumed"):
            raise APIReceiptIntegrityError("The exception's authorization effects differ from its reviewed invalidation plan")

    def _refuse_duplicate_request(self, bill_id, context):
        manifest = context.get("manifest") or self.cipher._manifest("bill.correct", bill_id, "accountant")
        for approval in self.cipher.approvals.list():
            if (approval["operation"] == "bill.correct" and approval["subject_id"] == bill_id
                    and approval["status"] in ("pending", "granted") and parse_iso(approval["expires_at"]) > utcnow()
                    and material_hash(manifest) == approval["material_hash"]
                    and manifest.get("governance") == approval["manifest"].get("governance")):
                self._approval_proof(approval["id"])
                raise APRefusal(409, "duplicate_open_approval", "This bill already has a current correction approval request.", approval["id"])

    def _approval_proof(self, approval_id):
        from .ap_exception_preflight import correction_approval_proof
        proof = correction_approval_proof(self.cipher, approval_id)
        approval = self.cipher.approvals.get(approval_id)
        if approval["operation"] != "bill.correct" or approval["actor_role"] != "accountant":
            raise APIReceiptIntegrityError("The fixed correction API requires an accountant correction authorization")
        return proof

    def _apply(self, action, resource_id, body, context):
        c, login, ap = self.cipher, context["login"], self.cipher.plugin("ap_intake")
        typed = self.preflight._body(action, body, action_body=True)
        source = {"kind": action, "resourceId": resource_id}
        result = {"journalDelta": 0, "apDeltaCents": 0}
        if action.startswith("invoice."):
            if action == "invoice.revise":
                evidence = self._evidence(typed["evidenceRevisionId"], context["projectId"])
                inv = ap.revise_invoice(resource_id, login, reason=typed["reason"], invoice_number=typed["invoiceNumber"],
                    invoice_date=typed["invoiceDate"], amount=Decimal(typed["amountCents"]) / 100, evidence_hash=evidence["content_hash"])
                event = self._version_event(resource_id, inv["version"])
                row = ap._row(resource_id)
                source.update(original={key: row[key] for key in INVOICE_CONTENT_FIELDS}, contentHash=row["content_hash"], event=event)
                result.update(invoiceId=resource_id, status="received", invoiceVersion=inv["version"], amountCents=_cents(inv["amount"]))
            elif action == "invoice.reject":
                inv = ap.reject_invoice(resource_id, typed["reason"], login)
                source["event"] = self._event("ap_intake.invoice_rejected", "ap_invoice", resource_id)
                result.update(invoiceId=resource_id, status="rejected", invoiceVersion=inv["version"])
            else:
                inv = ap.clear_duplicate_flag(resource_id, typed["reason"], login)
                events = c.db.query("SELECT * FROM audit_log WHERE action='ap_intake.duplicate_flag_cleared' AND entity_type='ap_invoice' AND entity_id=? ORDER BY seq", (resource_id,))
                event = events[-1]
                source["event"] = {"seq": event["seq"], "hash": event["entry_hash"]}
                result.update(invoiceId=resource_id, status="received", invoiceVersion=inv["version"], duplicateReviewed=True)
            return result, source
        if action == "bill.cancel":
            c.bills.void(resource_id, actor=login, reason=typed["reason"])
            source["event"] = self._event("bill.voided", "bill", resource_id)
            return dict(result, billId=resource_id, status="void"), source
        if action == "bill.prepareCorrection":
            request = c.bills.prepare_correction(resource_id, typed["reason"], login)
            source.update(correctionId=request["id"], original={key: request[key] for key in ("id", "bill_id", "reason", "requested_by", "requested_at")},
                          event=self._correction_event("bill.correction_requested", resource_id, request["id"]))
            return dict(result, billId=resource_id, correctionId=request["id"], status="pending"), source
        if action == "bill.requestCorrection":
            approval = c.request_approval("bill.correct", resource_id, actor_role="accountant", requested_by=login)
            source.update(approvalId=approval["id"], request=self._approval_proof(approval["id"]))
            return dict(result, billId=resource_id, approvalId=approval["id"], status="pending"), source
        if action == "bill.approveCorrection":
            c.approve(resource_id, approver=login, approver_role="accountant")
            approval = c.approvals.get(resource_id)
            source.update(approvalId=resource_id, billId=approval["subject_id"], request=self._approval_proof(resource_id),
                          event=self._event("approval.granted", "approval", resource_id))
            return dict(result, billId=approval["subject_id"], approvalId=resource_id, status="granted"), source
        c.check_bill_correction_execution(resource_id, actor=login, period_id=typed["periodId"])
        executed = c.execute(resource_id, actor=login, period_id=typed["periodId"])
        approval = c.approvals.get(resource_id)
        bill_id = approval["subject_id"]
        request_id = approval["manifest"]["bindings"]["request"]["id"]
        event = self._correction_event("bill.corrected", bill_id, request_id)
        payload = loads(self._event_row(event)["payload_json"])
        source.update(approvalId=resource_id, billId=bill_id, correctionId=request_id, request=self._approval_proof(resource_id),
                      event=event, commandId=executed.op_id, journals=[self._journal_source(jid) for jid in payload["reversal_journals"]])
        bill = c.bills.get(bill_id)
        return {"billId": bill_id, "approvalId": resource_id, "correctionId": request_id, "status": "corrected",
                "periodId": payload["period_id"], "reversalJournalIds": payload["reversal_journals"],
                "journalDelta": len(payload["reversal_journals"]), "apDeltaCents": -_cents(bill["amount_due"])}, source

    def _version_event(self, invoice_id, version):
        rows = self.cipher.db.query("SELECT * FROM audit_log WHERE action='ap_intake.invoice_revised' AND entity_type='ap_invoice' AND entity_id=? ORDER BY seq", (invoice_id,))
        rows = [row for row in rows if loads(row["payload_json"]).get("version") == version]
        if len(rows) != 1:
            raise APIReceiptIntegrityError("Invoice revision requires its unique original source event")
        return {"seq": rows[0]["seq"], "hash": rows[0]["entry_hash"]}

    def _correction_event(self, action, bill_id, correction_id):
        rows = self.cipher.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type='bill' AND entity_id=? ORDER BY seq", (action, bill_id))
        rows = [row for row in rows if loads(row["payload_json"]).get("request_id") == correction_id]
        if len(rows) != 1:
            raise APIReceiptIntegrityError("A correction requires its unique original source event")
        return {"seq": rows[0]["seq"], "hash": rows[0]["entry_hash"]}

    def _journal_source(self, journal_id):
        row = self.cipher.db.one("SELECT * FROM journals WHERE id=?", (journal_id,))
        if row is None:
            raise APIReceiptIntegrityError("The correction reversal journal is missing")
        return {"row": row, "lines": self.cipher.db.query("SELECT * FROM journal_lines WHERE journal_id=? ORDER BY line_no", (journal_id,)),
                "event": self._event("journal.posted", "journal", journal_id)}

    def _verify_source(self, row):
        action, resource = row["fixed_action"], row["resource_id"]
        if action not in ACTIONS:
            raise APIReceiptIntegrityError("An exception receipt has an unsupported fixed action")
        source, result, binding = loads(row["source_json"]), loads(row["result_json"]), loads(row["binding_json"])
        try:
            _key, expected = self._shape(action, resource, binding["canonicalTypedBody"], row["repeatability_uuid"], binding["originalIfMatch"])
        except (APRefusal, KeyError, TypeError, ValueError) as exc:
            raise APIReceiptIntegrityError("The exception receipt has an invalid original typed binding") from exc
        if binding != expected or row["contract_version"] != CONTRACT_VERSION:
            raise APIReceiptIntegrityError("The exception receipt differs from its original review metadata")
        person = self.cipher.plugin("people").person_for(row["actor_login"])
        if person is None or person["id"] != row["canonical_person_id"]:
            raise APIReceiptIntegrityError("The exception source has a different canonical actor")
        if source["kind"] == "refusal":
            return self._verify_refusal(row, source, result)
        if source["kind"] != action or source["resourceId"] != resource or row["outcome"] != "success" or row["http_status"] != 200:
            raise APIReceiptIntegrityError("The exception receipt has inconsistent domain outcome metadata")
        typed = self.preflight._body(action, binding["canonicalTypedBody"], action_body=True)
        expected = {"journalDelta": 0, "apDeltaCents": 0}
        if action.startswith("invoice."):
            self._verify_invoice_current(resource)
            event = self._event_row(source["event"])
            payload = loads(event["payload_json"])
            event_action = {"invoice.revise": "ap_intake.invoice_revised", "invoice.reject": "ap_intake.invoice_rejected",
                            "invoice.reviewDuplicate": "ap_intake.duplicate_flag_cleared"}[action]
            if (event["action"] != event_action or event["entity_type"] != "ap_invoice" or event["entity_id"] != resource
                    or event["actor"] != row["actor_login"] or payload.get("reason") != typed["reason"]):
                raise APIReceiptIntegrityError("The invoice exception differs from its original audited decision")
            if action == "invoice.revise":
                original = source["original"]
                if (original["id"] != resource or original["version"] != payload["version"]
                        or self.cipher.plugin("ap_intake")._content_hash(original) != source["contentHash"] or source["contentHash"] != payload["content_hash"]
                        or original["invoice_number"] != typed["invoiceNumber"] or original["invoice_date"] != typed["invoiceDate"]
                        or _cents(original["amount"]) != typed["amountCents"] or original["evidence_revision_id"] != typed["evidenceRevisionId"]):
                    raise APIReceiptIntegrityError("The revision's original content differs from its typed source")
                if "due_date" in payload["changes"]:
                    terms = original["terms_days"]
                    if (type(terms) is not int or not 0 <= terms <= 365
                            or original["due_date"] != (dt.date.fromisoformat(original["invoice_date"]) + dt.timedelta(days=terms)).isoformat()):
                        raise APIReceiptIntegrityError("The fixed revision source changed commercial terms outside its original route")
                expected.update(invoiceId=resource, status="received", invoiceVersion=payload["version"], amountCents=_cents(original["amount"]))
            else:
                if action == "invoice.reviewDuplicate" and payload.get("cleared_by") != row["actor_login"]:
                    raise APIReceiptIntegrityError("The duplicate review has a different original reviewer")
                expected.update(invoiceId=resource, status="rejected" if action == "invoice.reject" else "received", invoiceVersion=payload["version"])
                if action == "invoice.reviewDuplicate":
                    expected["duplicateReviewed"] = True
        elif action == "bill.cancel":
            bill = self.cipher.bills.get(resource)
            self._verify_bill(bill)
            event = self._event_row(source["event"])
            if (event["action"] != "bill.voided" or event["entity_type"] != "bill" or event["entity_id"] != resource
                    or event["actor"] != row["actor_login"] or loads(event["payload_json"]) != {"reason": typed["reason"]}):
                raise APIReceiptIntegrityError("The bill cancellation differs from its original decision")
            expected.update(billId=resource, status="void")
        elif action == "bill.prepareCorrection":
            correction = self.cipher.bills.correction_proof(source["correctionId"])
            self._verify_bill(self.cipher.bills.get(resource))
            event = self._event_row(source["event"])
            if ({key: correction[key] for key in source["original"]} != source["original"]
                    or correction["bill_id"] != resource or correction["reason"] != typed["reason"] or correction["requested_by"] != row["actor_login"]
                    or event["action"] != "bill.correction_requested" or event["entity_type"] != "bill" or event["entity_id"] != resource
                    or event["actor"] != row["actor_login"] or loads(event["payload_json"]) != {"request_id": correction["id"], "reason": typed["reason"]}):
                raise APIReceiptIntegrityError("The correction preparation differs from its original request")
            expected.update(billId=resource, correctionId=correction["id"], status="pending")
        else:
            approval = self.cipher.approvals.get(source["approvalId"])
            if source["request"] != self._approval_proof(approval["id"]):
                raise APIReceiptIntegrityError("The correction decision differs from its original approval")
            bill_id = approval["subject_id"]
            self._verify_bill(self.cipher.bills.get(bill_id))
            if action == "bill.requestCorrection":
                if resource != bill_id or approval["requested_by"] != row["actor_login"]:
                    raise APIReceiptIntegrityError("The correction approval request has inconsistent origin")
                expected.update(billId=bill_id, approvalId=approval["id"], status="pending")
            elif action == "bill.approveCorrection":
                event = self._event_row(source["event"])
                if (resource != approval["id"] or approval["approver"] != row["actor_login"] or event["action"] != "approval.granted"
                        or event["entity_type"] != "approval" or event["entity_id"] != resource or event["actor"] != row["actor_login"]
                        or loads(event["payload_json"]) != {"operation": "bill.correct", "material_hash": approval["material_hash"]}):
                    raise APIReceiptIntegrityError("The correction grant has no original independent decision")
                expected.update(billId=bill_id, approvalId=resource, status="granted")
            else:
                expected = self._correction_result(row, source, approval, typed)
        if result != expected:
            raise APIReceiptIntegrityError("The exception result differs from its original domain outcome")

    def _verify_bill(self, bill):
        try:
            self.contract.base._verify_bill(bill)
            self.cipher.bills.correction_inventory(bill["id"])
        except (APRefusal, BillError) as exc:
            raise APIReceiptIntegrityError("The bill's current lifecycle or original source cannot be verified") from exc

    def _correction_result(self, row, source, approval, typed):
        event = self._event_row(source["event"])
        payload = loads(event["payload_json"])
        bound = approval["manifest"]["bindings"]
        correction = self.cipher.bills.correction_proof(source["correctionId"])
        if (approval["status"] != "consumed" or approval["consumed_by"] != row["actor_login"] or source["approvalId"] != row["resource_id"]
                or event["action"] != "bill.corrected" or event["entity_type"] != "bill" or event["entity_id"] != approval["subject_id"]
                or event["actor"] != row["actor_login"] or payload["approval_id"] != approval["id"]
                or payload["request_id"] != bound["request"]["id"] or source["correctionId"] != bound["request"]["id"]
                or payload["reason"] != bound["reason"] or payload["period_id"] != typed["periodId"]
                or payload["amount_due"] != approval["manifest"]["amounts"]["amount_due"]
                or correction["status"] != "executed" or correction["approval_id"] != approval["id"]
                or correction["period_id"] != payload["period_id"] or correction["reversal_journals"] != payload["reversal_journals"]
                or payload["restored_lots"] or payload["unbilled_lots"]):
            raise APIReceiptIntegrityError("The correction differs from its original consumed installed-work approval")
        if [journal["row"]["id"] for journal in source["journals"]] != payload["reversal_journals"] or len(source["journals"]) != len(bound["journals"]):
            raise APIReceiptIntegrityError("The correction's original reversal inventory differs")
        for original, proof in zip(bound["journals"], source["journals"]):
            current = self._journal_source(proof["row"]["id"])
            predecessor = self.cipher.ledger.journal(original["id"])
            journal = proof["row"]
            if (current != proof or lines_fingerprint(predecessor["lines"]) != original["lines_fingerprint"]
                    or journal["reversal_of"] != original["id"] or journal["approval_id"] != approval["id"]
                    or journal["period_id"] != typed["periodId"] or journal["posted_by"] != row["actor_login"]):
                raise APIReceiptIntegrityError("The correction reversal no longer matches its approved journal source")
            expected_lines = [{"account_code": line["account_code"], "debit": line["credit"], "credit": line["debit"],
                "project_id": line["project_id"], "party_id": line["party_id"], "memo": f"reversal: {line['memo']}"} for line in predecessor["lines"]]
            actual_lines = [{key: line[key] for key in expected_lines[0]} for line in proof["lines"]]
            if actual_lines != expected_lines:
                raise APIReceiptIntegrityError("The correction reversal entries differ from the exact approved reversal")
            reversed_event = self._event("journal.reversed", "journal", original["id"])
            reversing = self._event_row(reversed_event)
            reversed_payload = loads(reversing["payload_json"])
            if (reversing["actor"] != row["actor_login"] or reversed_payload["reversal_journal_id"] != journal["id"]
                    or reversed_payload["approval_id"] != approval["id"] or reversed_payload["period_id"] != typed["periodId"]
                    or reversed_payload["reason"] != f"bill.correct {source['correctionId']}: {bound['reason']}"):
                raise APIReceiptIntegrityError("The correction reversal has no original audited execution")
        command = self.cipher.db.one("SELECT * FROM idempotency WHERE op_id=?", (source["commandId"],))
        command_payload = {"approval_id": approval["id"], "operation": "bill.correct", "subject_id": approval["subject_id"]}
        command_result = {"bill": approval["subject_id"], "status": "corrected", "request_id": source["correctionId"], "reason": bound["reason"],
            "period_id": payload["period_id"], "reversal_journals": payload["reversal_journals"], "restored_lots": [], "unbilled_lots": []}
        command_event = self._event_row(self._event("command.executed", "command", source["commandId"]))
        if (source["commandId"] != f"exec:{approval['id']}" or command is None or command["payload_hash"] != hash_json(command_payload)
                or command["result_json"] != canonical_json(command_result) or command_event["actor"] != row["actor_login"]
                or loads(command_event["payload_json"]) != {"payload_hash": hash_json(command_payload)}):
            raise APIReceiptIntegrityError("The correction command differs from its original governed result")
        return {"billId": approval["subject_id"], "approvalId": approval["id"], "correctionId": source["correctionId"], "status": "corrected",
            "periodId": payload["period_id"], "reversalJournalIds": payload["reversal_journals"], "journalDelta": len(payload["reversal_journals"]),
            "apDeltaCents": -_cents(payload["amount_due"])}

    def _terminal_refusal_proof(self, action, resource_id, context, before, exc):
        if action not in ("bill.approveCorrection", "bill.executeCorrection"):
            raise APIReceiptIntegrityError("An exception metadata failure cannot commit authorization control effects")
        # Reuse the exact state-delta validation with its fixed decision names;
        # the overridden proof method validates only bill.correct authorizations.
        equivalent = "invoice.approveMatch" if action == "bill.approveCorrection" else "invoice.executeMatch"
        return APIntakeActionRunner._terminal_refusal_proof(self, equivalent, resource_id, context, before, exc)

    def _verify_refusal(self, row, source, result):
        equivalent = dict(row, fixed_action="invoice.approveMatch" if row["fixed_action"] == "bill.approveCorrection" else "invoice.executeMatch")
        if row["fixed_action"] not in ("bill.approveCorrection", "bill.executeCorrection"):
            raise APIReceiptIntegrityError("An exception refusal has unsupported control proof")
        return APIntakeActionRunner._verify_refusal(self, equivalent, source, result)

    def _verify_effect_boundary(self, action, resource_id, before, receipt, source):
        after = self._control_snapshot()
        if before["schema"] != after["schema"] or before["tables"].keys() != after["tables"].keys():
            raise APIReceiptIntegrityError("An exception action changed the workspace schema")
        allowed = TABLES[action] | {"ap_action_receipts"}
        for table, value in before["tables"].items():
            if table not in allowed and after["tables"][table] != value:
                raise APIReceiptIntegrityError("An exception action produced an unreviewed financial or record effect")
        if before["audit"] != after["audit"][:len(before["audit"])]:
            raise APIReceiptIntegrityError("An exception action altered existing audit history")
        added = {"ap_action_receipts": {receipt["id"]}}
        changes, expected = {}, [("ap.practice_action_recorded", "ap_action_receipt", receipt["id"])]
        approval_changes = {}
        if source["kind"] == "refusal":
            approval_changes[resource_id] = {"status", "invalidated_reason"}
            expected.append((f"approval.{source['status']}", "approval", resource_id))
        elif action.startswith("invoice."):
            event = self._event_row(source["event"])
            expected.append((event["action"], "ap_invoice", resource_id))
            fields = ({"invoice_number", "number_key", "invoice_date", "due_date", "terms_days", "amount", "service_period_start", "service_period_end",
                       "evidence_hash", "evidence_document_id", "evidence_revision_id", "lines_json", "content_hash", "version", "status", "possible_duplicate",
                       "duplicate_of_json", "duplicate_cleared_by", "duplicate_cleared_at", "duplicate_clear_reason", "match_status", "match_basis",
                       "match_exceptions_json", "match_attempt_id", "updated_at"} if action == "invoice.revise" else
                      {"status", "rejected_by", "rejected_at", "reject_reason", "updated_at"} if action == "invoice.reject" else
                      {"duplicate_cleared_by", "duplicate_cleared_at", "duplicate_clear_reason", "updated_at"})
            changes["ap_invoices"] = {resource_id: fields}
        elif action == "bill.cancel":
            changes["bills"] = {resource_id: {"status"}}
            expected.append(("bill.voided", "bill", resource_id))
        elif action == "bill.prepareCorrection":
            added["bill_corrections"] = {source["correctionId"]}
            expected.append(("bill.correction_requested", "bill", resource_id))
        elif action == "bill.requestCorrection":
            added["approvals"] = {source["approvalId"]}
            expected.append(("approval.requested", "approval", source["approvalId"]))
        elif action == "bill.approveCorrection":
            approval_changes[resource_id] = {"status", "approver", "granted_at"}
            expected.append(("approval.granted", "approval", resource_id))
        else:
            bill_id, correction_id = source["billId"], source["correctionId"]
            approval_changes[resource_id] = {"status", "consumed_by", "consumed_at"}
            changes["bills"] = {bill_id: {"status", "correction_id", "corrected_at"}}
            changes["bill_corrections"] = {correction_id: {"status", "approval_id", "period_id", "reversal_journals_json", "resolved_by", "resolved_at", "resolution_note"}}
            added["idempotency"] = {source["commandId"]}
            added["journals"] = {proof["row"]["id"] for proof in source["journals"]}
            added["journal_lines"] = {line["id"] for proof in source["journals"] for line in proof["lines"]}
            expected.extend((("approval.consumed", "approval", resource_id), ("bill.corrected", "bill", bill_id),
                             ("command.executed", "command", source["commandId"])))
            original_ids = {proof["row"]["reversal_of"] for proof in source["journals"]}
            for proof in source["journals"]:
                expected.extend((("journal.posted", "journal", proof["row"]["id"]), ("journal.reversed", "journal", proof["row"]["reversal_of"])))
            for request in before["effectRows"]["journal_reversal_requests"]:
                if request["journal_id"] in original_ids and request["status"] == "pending":
                    changes.setdefault("journal_reversal_requests", {})[request["id"]] = {"status", "reversal_journal_id", "resolved_by", "resolved_at", "resolution_note"}
        # Only this original subject's open approvals may be invalidated by the
        # domain action. A new request or a different bill/invoice is never allowed.
        old = {r["id"]: r for r in before["approvals"]}
        new = {r["id"]: r for r in after["approvals"]}
        invalidating = action in ("invoice.revise", "invoice.reject", "bill.cancel", "bill.executeCorrection") and source["kind"] != "refusal"
        subject = source.get("billId", resource_id)
        subject_type = "ap_invoice" if action.startswith("invoice.") else "bill"
        for key in old.keys() & new.keys():
            if old[key] == new[key] or key in approval_changes:
                continue
            if (not invalidating or old[key]["subject_type"] != subject_type or old[key]["subject_id"] != subject
                    or old[key]["status"] not in ("pending", "granted") or new[key]["status"] != "invalidated"):
                raise APIReceiptIntegrityError("An exception action changed an unrelated authorization")
            approval_changes[key] = {"status", "invalidated_reason"}
            expected.append(("approval.invalidated", "approval", key))
        changes["approvals"] = approval_changes
        for table in before["effectRows"]:
            self._row_effect(before, after, table, added=added.get(table, ()), changed=changes.get(table))
        tail = after["audit"][len(before["audit"]):]
        if (Counter((event["action"], event["entity_type"], event["entity_id"]) for event in tail) != Counter(expected)
                or any(event["actor"] != receipt["actor_login"] for event in tail)):
            raise APIReceiptIntegrityError("An exception action appended an unreviewed audit effect")

    def _records(self):
        return self.cipher.db.query("SELECT * FROM ap_action_receipts WHERE fixed_action IN (?,?,?,?,?,?,?,?) ORDER BY created_at,id", tuple(sorted(ACTIONS)))

    def integrity_checks(self):
        checks = self.receipts.integrity_checks()
        if not checks[0]["ok"]:
            return checks
        try:
            for row in self._records():
                self._verify_source(row)
        except Exception:
            return [{"ok": False, "code": "ap_exception_sources_integrity", "message": "AP exception outcomes have inconsistent original source proof"}]
        return checks + [{"ok": True, "code": "ap_exception_sources_integrity", "message": "AP exception outcomes match their original audited domain proof"}]
