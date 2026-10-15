"""Seven fixed local owner-billing effects, original proofs and atomic receipts.

Scratch prototype. No import registration, provider dispatch or general operation
selector. Current own project duty precedes namespace or receipt disclosure.
"""
from collections import Counter
from contextlib import contextmanager
from uuid import UUID

from .ap_contract import APRefusal
from .core.api_receipts import APIActionReceipts, APIRepeatabilityConflict
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow
from .core.money import D, fmt, money
from .domain.receivables import ReceivableError
from .domain.owner_billing_calculation import OwnerProgressLine, calculate_owner_pay_app
from .domain.owner_billing import FIXED_SOV
from .ar_receipts import ARReceipts, ARReceiptError, RECEIPT_ACTION, RECEIPT_ENTITY
from .ar_wire import ACTIONS, CONTRACT_VERSION



class ARActionRunner:
    def __init__(self, cipher, contract, preflight):
        if contract.cipher is not cipher or preflight.cipher is not cipher or preflight.contract is not contract:
            raise ValueError("AR actions require one owned scoped runtime")
        self.cipher, self.contract, self.preflight = cipher, contract, preflight
        self.domain = cipher.plugin("owner_billing")
        self.receipts = ARReceipts(cipher.db, cipher.audit)

    @contextmanager
    def _transaction(self):
        with self.cipher.db.transaction() as conn:
            name = new_id("ar_api")
            conn.execute(f"SAVEPOINT {name}")
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:
                    conn.execute(f"ROLLBACK TO {name}")
                raise
            finally:
                if conn.in_transaction:
                    conn.execute(f"RELEASE {name}")

    def _shape(self, action, resource_id, body, key, if_match):
        if type(action) is not str or action not in ACTIONS or type(resource_id) is not str or not resource_id or len(resource_id) > 160:
            raise APRefusal(422, "invalid_action", "Choose a supported owner-billing action.", "action")
        try:
            normalized = str(UUID(key)) if type(key) is str and len(key) == 36 else None
        except (ValueError, AttributeError):
            normalized = None
        if normalized is None or normalized != key.casefold():
            raise APRefusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.", "Repeatability-Request-ID")
        if type(if_match) is not str or not if_match or len(if_match) > 256:
            raise APRefusal(422, "missing_record_version", "Supply the owner-billing version reviewed for this action.", "If-Match")
        typed = self.preflight._body(action, body, effect=True)
        fingerprint = body.get("fingerprint")
        if type(fingerprint) is not str or not fingerprint or not fingerprint.isascii() or len(fingerprint) > 256:
            raise APRefusal(422, "invalid_fingerprint", "Supply the original owner-billing review fingerprint.", "fingerprint")
        return normalized, {"contractVersion": CONTRACT_VERSION, "fixedAction": action, "resourceId": resource_id,
                            "canonicalTypedBody": {**typed, "fingerprint": fingerprint}, "originalIfMatch": if_match,
                            "preflightFingerprint": fingerprint}

    def _namespace(self, person_id, key, action, binding):
        # Future same-workspace composition must not steal an existing AP key or
        # pending worker reservation. These calls are metadata-only and follow
        # current owner-billing authorization. The dedicated server seeds none.
        ap = APIActionReceipts(self.cipher.db, self.cipher.audit)
        ap.require_repeatability_namespace(person_id, key, action, binding)
        if ap.find(person_id, key) is not None:
            raise APIRepeatabilityConflict("This key belongs to its original AP request")

    def run(self, person_id, action, resource_id, body, *, repeatability_key, if_match):
        key, binding = self._shape(action, resource_id, body, repeatability_key, if_match)
        deferred, response = None, None
        try:
            with self._transaction():
                self.cipher.db.require_practice_mode()
                self.cipher.db.require_write_authority()
                if not self.cipher.db.in_memory:
                    raise PermissionError("AR practice effects require disposable memory")
                context = self.contract.authorize(person_id, action, resource_id)
                self._namespace(context["personId"], key, action, binding)
                receipt = self.receipts.find(context["personId"], key)
                if receipt is not None:
                    if receipt["binding_json"] != canonical_json(binding):
                        raise APRefusal(409, "repeatability_conflict", "This key belongs to a different original reviewed request.")
                    self._verify_source(receipt)
                    if receipt["outcome"] == "refused":
                        deferred = self._stored_refusal(receipt, replayed=True)
                    else:
                        response = self._response(receipt, replayed=True)
                else:
                    review_started = utcnow()
                    verified = self.preflight.verify(person_id, action, resource_id, body, if_match)
                    if any(verified[key] != context[key] for key in ("personId", "login", "duty", "operationRole", "projectId")):
                        raise ARReceiptError("AR authority changed within the locked review")
                    # Freeze mutable prospective facts before an effect callback
                    # can attempt to change its own expected plan.
                    reviewed = loads(canonical_json({key: verified[key] for key in ("personId", "login", "duty", "operationRole", "projectId", "typed", "plan", "sourceFacts", "manifest", "review")}))
                    reviewed["reviewClockStartedAt"] = review_started.isoformat()
                    plan = reviewed["plan"]
                    before = self._snapshot()
                    try:
                        result, source = self._apply(action, resource_id, verified)
                        self._verify_plan(action, resource_id, reviewed, plan, source)
                        source["reviewedPlanHash"] = hash_json(plan)
                        source["reviewedSourceHash"] = hash_json(reviewed["sourceFacts"])
                    except (StaleApprovalError, ApprovalExpired) as exc:
                        source = self._terminal_proof(action, resource_id, context, before, exc)
                        status = 423 if isinstance(exc, ApprovalExpired) else 412
                        result = {"code": "owner_authorization_expired" if status == 423 else "owner_source_changed",
                                  "message": "The owner-billing authorization expired. Request fresh review." if status == 423
                                  else "The owner-billing source changed. Request fresh review.", "target": "approval"}
                        receipt = self._record(context, key, action, resource_id, binding, result, source,
                                               outcome="refused", http_status=status)
                        self._verify_source(receipt)
                        self._verify_boundary(action, resource_id, context, before, receipt, source)
                        deferred = self._stored_refusal(receipt, replayed=False)
                    else:
                        receipt = self._record(context, key, action, resource_id, binding, result, source)
                        self._verify_source(receipt)
                        self._verify_boundary(action, resource_id, context, before, receipt, source)
                        response = self._response(receipt, replayed=False)
        except APRefusal:
            raise
        except APIRepeatabilityConflict:
            raise APRefusal(409, "repeatability_conflict", "This key belongs to a different original reviewed request.") from None
        except PermissionError:
            raise APRefusal(403, "action_not_authorized", "Your current project duties do not permit this owner-billing action.") from None
        except (ApprovalError, ReceivableError):
            raise APRefusal(409, "action_refused", "This owner-billing action cannot proceed. Refresh its review.") from None
        except Exception:
            raise APRefusal(500, "action_unavailable", "The action did not complete. Retry the same reviewed request.") from None
        if deferred:
            raise deferred
        if response is None:
            raise APRefusal(500, "action_unavailable", "The action did not complete. Retry the same reviewed request.")
        return response

    def _record(self, context, key, action, resource_id, binding, result, source, *, outcome="success", http_status=200):
        arguments = {"person_id": context["personId"], "actor_login": context["login"], "repeatability_uuid": key,
                     "action": action, "resource_id": resource_id, "binding": binding, "result": result, "source": source,
                     "outcome": outcome, "http_status": http_status}
        expected = loads(canonical_json(arguments))
        workspace = self.cipher.db.mode_status()["workspace_id"]
        returned = self.receipts.record(**arguments)
        stored = self.cipher.db.one("SELECT * FROM ar_action_receipts WHERE id=?", (returned["id"],))
        fields = {"workspace_id": workspace, "canonical_person_id": expected["person_id"], "actor_login": expected["actor_login"],
                  "repeatability_uuid": expected["repeatability_uuid"], "contract_version": CONTRACT_VERSION,
                  "fixed_action": expected["action"], "resource_id": expected["resource_id"],
                  "binding_json": canonical_json(expected["binding"]), "result_json": canonical_json(expected["result"]),
                  "source_json": canonical_json(expected["source"]), "outcome": expected["outcome"], "http_status": expected["http_status"]}
        if (stored is None or not self._same(stored, returned) or not self._same(arguments, expected)
                or any(not self._same(stored[field], value) for field, value in fields.items())):
            raise ARReceiptError("Owner-billing receipt changed its exact original reviewed invocation")
        self.receipts.verify_integrity()
        return stored

    @staticmethod
    def _response(receipt, *, replayed):
        return {"receiptId": receipt["id"], "replayed": replayed, "effectApplied": not replayed, "result": loads(receipt["result_json"])}

    @staticmethod
    def _stored_refusal(receipt, *, replayed):
        result = loads(receipt["result_json"])
        error = APRefusal(receipt["http_status"], result["code"], result["message"], result["target"])
        error.receipt_id, error.replayed, error.effect_applied = receipt["id"], replayed, False
        return error

    def _event(self, action, kind, identifier):
        rows = self.cipher.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type=? AND entity_id=? ORDER BY seq", (action, kind, identifier))
        if len(rows) != 1:
            raise ARReceiptError("AR effect requires one original audited event")
        return {"auditSeq": rows[0]["seq"], "auditHash": rows[0]["entry_hash"]}

    def _event_row(self, ref, *, with_actor=False):
        fields = {"auditSeq", "auditHash", "actor"} if with_actor else {"auditSeq", "auditHash"}
        if (type(ref) is not dict or set(ref) != fields
                or type(ref["auditSeq"]) is not int or ref["auditSeq"] <= 0
                or type(ref["auditHash"]) is not str):
            raise ARReceiptError("AR original effect requires its exact integer audit reference")
        row = self.cipher.db.one("SELECT * FROM audit_log WHERE seq=?", (ref["auditSeq"],))
        if (row is None or row["entry_hash"] != ref["auditHash"]
                or with_actor and (type(ref["actor"]) is not str or row["actor"] != ref["actor"])):
            raise ARReceiptError("AR original effect event disappeared")
        return row

    @staticmethod
    def _same(left, right):
        return canonical_json(left) == canonical_json(right)

    def _approval_proof(self, approval_id):
        return self.domain.approval_proof(approval_id)

    def _request_proof(self, approval_id):
        proof = self._approval_proof(approval_id)
        ap = proof["approval"]
        return {"requestEvent": proof["requestEvent"], "manifestHash": ap["manifest_hash"], "materialHash": ap["material_hash"],
                "requestedBy": ap["requested_by"], "requestedAt": ap["requested_at"], "expiresAt": ap["expires_at"]}

    def _apply(self, action, resource_id, context):
        actor, role = context["login"], context["operationRole"]
        if action == "ownerBill.prepare":
            result = self.domain.prepare(resource_id, context["typed"], actor=actor)
            original = self.domain.source_proof(result["primeBillId"])
            source = {"kind": "prepare", "billId": result["primeBillId"], "basisId": resource_id, "record": original["record"]}
        elif action in ("ownerBill.requestApproval", "ownerBill.requestSend"):
            operation = "prime_bill.approve" if action == "ownerBill.requestApproval" else "prime_bill.send"
            operation_role = "accountant" if operation == "prime_bill.approve" else context["manifest"]["actor_role"]
            approval = self.cipher.request_approval(operation, resource_id, actor_role=operation_role, requested_by=actor)
            source = {"kind": "request", "billId": resource_id, "approvalId": approval["id"], "operation": operation,
                      "request": self._request_proof(approval["id"])}
        elif action in ("ownerBill.approve", "ownerBill.approveSend"):
            self.cipher.approve(resource_id, approver=actor, approver_role=role)
            approval = self.cipher.approvals.get(resource_id)
            source = {"kind": "grant", "billId": approval["subject_id"], "approvalId": resource_id, "operation": approval["operation"],
                      "request": self._request_proof(resource_id), "event": self._event("approval.granted", "approval", resource_id)}
            if action == "ownerBill.approve":
                source["record"] = self.domain.grant_proof(approval["subject_id"], approval_id=resource_id)["record"]
        elif action == "ownerBill.post":
            self.cipher.post_prime_bill(resource_id, actor=actor)
            record = self.domain.posting_receipt(resource_id)
            if record is None:
                raise ARReceiptError("Owner posting lacks its original immutable receipt")
            source = {"kind": "post", "billId": resource_id, "approvalId": record["approval_id"], "record": record,
                      "commandId": "prime_bill.post:" + resource_id + ":" + record["approval_id"]}
        else:
            approval = self.cipher.approvals.get(resource_id)
            self.cipher.execute(resource_id, actor=actor)
            source = {"kind": "send", "billId": approval["subject_id"], "approvalId": resource_id,
                      "record": self._send_proof(approval["subject_id"], resource_id), "commandId": "exec:" + resource_id,
                      "request": self._request_proof(resource_id)}
        return self._expected_result(action, source), source

    def _expected_result(self, action, source):
        result = {"action": action, "billId": source["billId"], "journalCountDelta": 0, "arBalanceDeltaCents": 0,
                  "retainedArDeltaCents": 0, "providerCallsDelta": 0}
        if action == "ownerBill.prepare":
            calculation = source["record"]["calculation"]
            result.update(status="draft", basisId=source["basisId"], amountDueCents=calculation["amountDueCents"],
                          reviewedCertifiedCents=calculation["reviewedCertifiedCents"])
        elif action in ("ownerBill.requestApproval", "ownerBill.requestSend"):
            result.update(status="pending", approvalId=source["approvalId"])
        elif action in ("ownerBill.approve", "ownerBill.approveSend"):
            result.update(status="granted", approvalId=source["approvalId"])
            if action == "ownerBill.approve":
                result.update(billStatus="draft", businessApprovalRecordId=source["record"]["id"])
        elif action == "ownerBill.post":
            calculation = self.domain.source_proof(source["billId"])["calculation"]
            record = source["record"]
            result.update(status="posted", approvalId=source["approvalId"], postingReceiptId=record["id"],
                          journalId=record["journal"]["header"]["id"], postingPeriodId=record["period"]["id"],
                          amountDueCents=calculation["amountDueCents"], journalCountDelta=1,
                          arBalanceDeltaCents=calculation["amountDueCents"], retainedArDeltaCents=calculation["retainageThisPeriodCents"])
        else:
            result.update(status="sent", approvalId=source["approvalId"], sendId=source["record"]["id"],
                          syntheticMailSink=True, externalDelivery="not_attempted")
        return result

    def _verify_prepare_input(self, basis_id, typed, proof):
        record, calculation = proof["record"], proof["calculation"]
        if (record["basis_id"] != basis_id or record["claim"]["revision"]["id"] != typed["claimRevisionId"]
                or record["review"]["revision"]["id"] != typed["reviewRevisionId"] or record["period"]["id"] != typed["periodId"]):
            raise ARReceiptError("Original owner certification differs from its typed source references")
        old = {line["lineId"]: line for line in calculation["lines"]}
        progress, locators = [], []
        for line in typed["lines"]:
            prior = old[line["lineId"]]
            previous = prior["previousQuantity"] if prior["basis"] == "unitPrice" else fmt(D(prior["previousAmountCents"])/100)
            progress.append(OwnerProgressLine(line["lineId"], previous, line["claimedCumulative"], line["reviewedCumulative"], line["differenceReason"].strip()))
            locators.append({"lineId": line["lineId"], "claimSourceLocator": line["claimSourceLocator"].strip(), "reviewSourceLocator": line["reviewSourceLocator"].strip()})
        rebuilt = calculate_owner_pay_app(sov_lines=FIXED_SOV, progress_lines=progress,
            prime_contract_value_cents=calculation["primeContractValueCents"], prior_retained_cents=calculation["priorRetainedCents"],
            retainage_released_cents=calculation["retainageReleasedCents"], retainage_rate=calculation["retainageRate"]).as_dict()
        if not self._same(rebuilt, calculation) or not self._same(record["locators"], locators):
            raise ARReceiptError("Original owner line quantities, reasons or locators differ from their typed input")

    def _verify_plan(self, action, resource_id, context, plan, source):
        if action == "ownerBill.prepare":
            proof = self.domain.source_proof(source["billId"])
            self._verify_prepare_input(resource_id, context["typed"], proof)
            record = proof["record"]
            keys = ("claim", "review", "period", "invoiceDate", "datePolicy", "calculation", "locators", "previousSourceId", "previousSourceHash")
            if (any(not self._same(record[key], plan[key]) for key in keys) or record["basisHash"] != plan["basis"]["basisHash"]
                    or record["actor"] != context["login"] or record["personId"] != context["personId"]):
                raise ARReceiptError("Owner preparation differs from its full reviewed source/calculation plan")
        elif action in ("ownerBill.requestApproval", "ownerBill.requestSend"):
            ap = self.cipher.approvals.get(source["approvalId"])
            if ap["material_hash"] != material_hash(context["manifest"]) or not self._same(ap["manifest"].get("governance"), context["manifest"].get("governance")):
                raise ARReceiptError("Owner request differs from its reviewed material/governance")
            source["requestDeadline"] = {"checkedExpiresAt": context["manifest"]["expires_at"],
                "reviewStartedAt": context["reviewClockStartedAt"], "completedAt": utcnow().isoformat()}
            self._verify_request_deadline(ap, source["requestDeadline"])
        elif action in ("ownerBill.approve", "ownerBill.approveSend"):
            ap = self.cipher.approvals.get(resource_id)
            if ap["material_hash"] != material_hash(context["manifest"]) or not self._same(ap["manifest"].get("governance"), context["manifest"].get("governance")):
                raise ARReceiptError("Owner grant differs from its reviewed material/governance")
        elif action == "ownerBill.post":
            record = source["record"]
            bound = context["manifest"]["bindings"]
            due = self.cipher.receivables._plus_days(plan["invoiceDate"], bound["payment_terms_days"])
            actual = [{"account": line["account_code"], "debit": line["debit"], "credit": line["credit"],
                       "project_id": line["project_id"], "party_id": line["party_id"], "memo": line["memo"]} for line in record["journal"]["lines"]]
            if (record["invoiceDate"] != plan["invoiceDate"] or record["dueDate"] != due
                    or type(record["termsDays"]) is not int or record["termsDays"] != bound["payment_terms_days"]
                    or record["period"]["id"] != plan["postingPeriodId"] or record["actor"] != context["login"]
                    or not self._same(self.cipher.receivables._preview(actual), bound["journal_preview"])):
                raise ARReceiptError("Owner posting differs from its complete reviewed journal/date/terms plan")
        else:
            bound = context["manifest"]["bindings"]
            if source["record"]["message_hash"] != bound["message_hash"] or not self._same(source["record"]["recipients"], bound["recipients"]):
                raise ARReceiptError("Owner send differs from its exact reviewed original message and recipients")

    def _send_proof(self, bill_id, approval_id):
        proof = self.domain.send_proof(bill_id)
        if proof is None or proof["record"]["approval_id"] != approval_id:
            raise ARReceiptError("Owner-send record lost its original fixed message authorization")
        return proof["record"]

    def _verify_source(self, receipt):
        action, resource_id, actor = receipt["fixed_action"], receipt["resource_id"], receipt["actor_login"]
        source, result, binding = (loads(receipt[key]) for key in ("source_json", "result_json", "binding_json"))
        typed = self.preflight._body(action, binding["canonicalTypedBody"], effect=True)
        if source["kind"] == "refusal":
            self._verify_refusal(receipt, source, result)
            return
        if receipt["outcome"] != "success" or receipt["http_status"] != 200:
            raise ARReceiptError("Owner action has no verified successful original effect")
        original = self.domain.source_proof(source["billId"])
        self.domain.approval_inventory(project_ids=(original["projectId"],))
        posting = self.domain.posting_receipt(source["billId"])
        if posting is not None:
            self.domain.send_proof(source["billId"])
        if action == "ownerBill.prepare":
            if (source["kind"] != "prepare" or source["basisId"] != resource_id or not self._same(source["record"], original["record"])
                    or source["record"]["actor"] != actor):
                raise ARReceiptError("Owner preparation lost its original immutable certification source")
            self._verify_prepare_input(resource_id, typed, original)
        elif action in ("ownerBill.requestApproval", "ownerBill.requestSend", "ownerBill.approve", "ownerBill.approveSend"):
            approval = self.cipher.approvals.get(source["approvalId"])
            expected_operation = "prime_bill.approve" if action in ("ownerBill.requestApproval", "ownerBill.approve") else "prime_bill.send"
            if (source["operation"] != expected_operation or approval["operation"] != expected_operation
                    or approval["subject_id"] != source["billId"] or not self._same(self._request_proof(source["approvalId"]), source["request"])):
                raise ARReceiptError("Owner action lost its original fixed authorization source")
            # Genuine older AR75 receipts retain their original serialized
            # source. New request effects additionally preserve this checked
            # native generation window without changing native TTL policy.
            if action in ("ownerBill.requestApproval", "ownerBill.requestSend") and "requestDeadline" in source:
                self._verify_request_deadline(approval, source["requestDeadline"], created_at=receipt["created_at"])
            if action in ("ownerBill.requestApproval", "ownerBill.requestSend"):
                if source["kind"] != "request" or source["billId"] != resource_id or approval["requested_by"] != actor:
                    raise ARReceiptError("Owner request lost its original requester attribution")
            else:
                event = self._event_row(source["event"])
                if (source["kind"] != "grant" or source["approvalId"] != resource_id or approval["approver"] != actor
                        or event["action"] != "approval.granted" or event["entity_id"] != resource_id or event["actor"] != actor):
                    raise ARReceiptError("Owner grant lost its original independent reviewer attribution")
                if action == "ownerBill.approve" and not self._same(self.domain.grant_proof(source["billId"], approval_id=resource_id)["record"], source["record"]):
                    raise ARReceiptError("Owner grant lost its original journal-free business record")
        elif action == "ownerBill.post":
            actual = self.domain.posting_receipt(resource_id)
            if source["kind"] != "post" or source["billId"] != resource_id or not self._same(actual, source["record"]) or actual["actor"] != actor:
                raise ARReceiptError("Owner posting lost its original same-grant journal receipt")
            self._verify_posting(source, actor)
            self._verify_command(source, actor)
        else:
            actual = self._send_proof(source["billId"], resource_id)
            if source["kind"] != "send" or source["approvalId"] != resource_id or not self._same(actual, source["record"]) or actual["sent_by"] != actor:
                raise ARReceiptError("Owner send lost its original exact synthetic message")
            self._verify_command(source, actor)
        if not self._same(result, self._expected_result(action, source)):
            raise ARReceiptError("Owner action result differs from its exact original source outcome")

    def _verify_posting(self, source, actor):
        record, bill_id = source["record"], source["billId"]
        original = self.domain.source_proof(bill_id)
        bill = original["bill"]
        grant = self.domain.grant_proof(bill_id, approval_id=source["approvalId"])
        bound = grant["record"]["originalManifest"]["bindings"]
        journal, lines = record["journal"]["header"], record["journal"]["lines"]
        expected_header = {"period_id": bill["period_id"], "description": f"Prime bill {bill['sequence']}",
            "source_type": "prime_bill", "source_id": bill_id, "source_version": "1", "rule_version": bound["posting_rule"],
            "approval_id": source["approvalId"], "reversal_of": None, "posted_by": actor, "line_count": len(lines)}
        native = self.cipher.receivables._bill_lines(bill)
        expected_lines = [{"line_no": number, "account_code": line["account"], "debit": fmt(line.get("debit", "0")),
                           "credit": fmt(line.get("credit", "0")), "project_id": bill["project_id"], "party_id": bill["customer_id"],
                           "memo": line.get("memo", "")} for number, line in enumerate(native, 1)]
        if (not self._same({key: journal[key] for key in expected_header}, expected_header)
                or not self._same([{key: line[key] for key in expected_lines[0]} for line in lines], expected_lines)
                or any(line["journal_id"] != journal["id"] for line in lines)
                or record["invoiceDate"] != bound["invoice_date"]
                or record["dueDate"] != self.cipher.receivables._plus_days(bound["invoice_date"], bound["payment_terms_days"])
                or not self._same(record["termsDays"], bound["payment_terms_days"])):
            raise ARReceiptError("Original owner journal/header/scope or dates differ from the same reviewed grant")
        journal_event = self._event_row(self._event("journal.posted", "journal", journal["id"]))
        posted_event = self._event_row(self._event("prime_bill.posted", "prime_bill", bill_id))
        total = fmt(sum((money(line["debit"]) for line in lines), money("0")))
        expected_journal = {"period_id": bill["period_id"], "source_type": "prime_bill", "source_id": bill_id, "source_version": "1",
                            "total": total, "approval_id": source["approvalId"], "reversal_of": None, "line_count": len(lines)}
        expected_post = {"approval_id": source["approvalId"], "journal_id": journal["id"], "contract_version": bill["contract_version"],
                         "invoice_date": record["invoiceDate"], "due_date": record["dueDate"], "payment_terms_days": record["termsDays"],
                         "payment_terms_version": bound["payment_terms_version"]}
        if (journal_event["actor"] != actor or posted_event["actor"] != actor
                or not self._same(loads(journal_event["payload_json"]), expected_journal)
                or not self._same(loads(posted_event["payload_json"]), expected_post)):
            raise ARReceiptError("Original owner posting audit differs from its reviewed journal and terms")

    def _verify_request_deadline(self, approval, clock, *, created_at=None):
        if type(clock) is not dict or set(clock) != {"checkedExpiresAt", "reviewStartedAt", "completedAt"} or any(type(v) is not str for v in clock.values()):
            raise ARReceiptError("Owner request lost its original checked policy clock")
        checked, actual, start, end, requested = (parse_iso(v) for v in
            (clock["checkedExpiresAt"], approval["expires_at"], clock["reviewStartedAt"], clock["completedAt"], approval["requested_at"]))
        if any(v.utcoffset() is None for v in (checked, actual, start, end, requested)):
            raise ARReceiptError("Owner policy clocks require original timezone provenance")
        elapsed, shifted = (end-start).total_seconds(), (actual-checked).total_seconds()
        observed_seconds = int(end.timestamp()) - int(start.timestamp())
        precision_window = elapsed if checked.microsecond or actual.microsecond else observed_seconds
        if (elapsed < 0 or shifted < 0 or shifted > precision_window
                or checked < start or (requested-start).total_seconds() < -1 or (requested-end).total_seconds() > 1
                or created_at is not None and (parse_iso(created_at)-end).total_seconds() < -1):
            raise ARReceiptError("Owner request changed its checked native policy deadline")

    def _verify_command(self, source, actor):
        if source["kind"] == "post":
            record = source["record"]
            payload = {"operation": "prime_bill.post", "prime_bill_id": source["billId"], "approval_id": source["approvalId"],
                       "period_id": record["period"]["id"], "person_id": record["posterPersonId"], "actor": actor}
            result = {"primeBillId": source["billId"], "postingReceiptId": record["id"], "journalId": record["journal"]["header"]["id"],
                      "periodId": record["period"]["id"], "status": "posted", "mode": "practice", "synthetic": True}
        else:
            payload = {"approval_id": source["approvalId"], "operation": "prime_bill.send", "subject_id": source["billId"]}
            result = {"prime_bill": source["billId"], "status": "sent", "send_id": source["record"]["id"], "channel": "mail-sink",
                      "recipients": source["record"]["recipients"]}
        row = self.cipher.db.one("SELECT * FROM idempotency WHERE op_id=?", (source["commandId"],))
        event = self._event_row(self._event("command.executed", "command", source["commandId"]))
        if (row is None or row["payload_hash"] != hash_json(payload) or row["result_json"] != canonical_json(result)
                or event["actor"] != actor or not self._same(loads(event["payload_json"]), {"payload_hash": hash_json(payload)})):
            raise ARReceiptError("Owner-billing command differs from its original exact payload/result/audit")

    def _snapshot(self):
        names = self.cipher.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return {"schema": self.cipher.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"),
                "tables": {row["name"]: self.cipher.db.query('SELECT * FROM "' + row["name"].replace('"', '""') + '"') for row in names}}

    def _verify_boundary(self, action, resource_id, context, before, receipt, source, *, after=None):
        after = self._snapshot() if after is None else after
        if before["schema"] != after["schema"] or before["tables"].keys() != after["tables"].keys():
            raise ARReceiptError("Owner-billing action changed the workspace schema")
        added, changed, expected_audit = {}, {}, []
        if receipt is not None:
            added["ar_action_receipts"] = {receipt["id"]}
            expected_audit.append((RECEIPT_ACTION, RECEIPT_ENTITY, receipt["id"]))
        if source["kind"] == "refusal":
            approval_id = source["approvalId"]
            changed["approvals"] = {approval_id: {"status", "invalidated_reason"}}
            expected_audit.append(("approval." + source["status"], "approval", approval_id))
        elif action == "ownerBill.prepare":
            added.update(prime_bills={source["billId"]}, owner_billing_sources={source["record"]["id"]})
            expected_audit += [("prime_bill.certified", "prime_bill", source["billId"]),
                               ("owner_billing.sources_recorded", "owner_billing_sources", source["record"]["id"])]
        elif action in ("ownerBill.requestApproval", "ownerBill.requestSend"):
            added["approvals"] = {source["approvalId"]}
            expected_audit.append(("approval.requested", "approval", source["approvalId"]))
        elif action in ("ownerBill.approve", "ownerBill.approveSend"):
            changed["approvals"] = {source["approvalId"]: {"status", "approver", "granted_at"}}
            expected_audit.append(("approval.granted", "approval", source["approvalId"]))
            if action == "ownerBill.approve":
                added["owner_billing_grants"] = {source["record"]["id"]}
                expected_audit.append(("owner_billing.grants_recorded", "owner_billing_grants", source["record"]["id"]))
        elif action == "ownerBill.post":
            record, journal = source["record"], source["record"]["journal"]
            added.update(journals={journal["header"]["id"]}, journal_lines={row["id"] for row in journal["lines"]},
                         owner_billing_postings={record["id"]}, idempotency={source["commandId"]})
            changed.update(approvals={source["approvalId"]: {"status", "consumed_by", "consumed_at"}},
                           prime_bills={source["billId"]: {"status", "approval_id", "journal_id", "invoice_date", "due_date", "payment_terms_days"}})
            expected_audit += [("approval.consumed", "approval", source["approvalId"]), ("journal.posted", "journal", journal["header"]["id"]),
                               ("prime_bill.posted", "prime_bill", source["billId"]), ("owner_billing.postings_recorded", "owner_billing_postings", record["id"]),
                               ("command.executed", "command", source["commandId"])]
        else:
            added.update(prime_bill_sends={source["record"]["id"]}, idempotency={source["commandId"]})
            changed.update(approvals={source["approvalId"]: {"status", "consumed_by", "consumed_at"}}, prime_bills={source["billId"]: {"status"}})
            expected_audit += [("approval.consumed", "approval", source["approvalId"]), ("prime_bill.sent", "prime_bill", source["billId"]),
                               ("command.executed", "command", source["commandId"])]
        for table, old_rows in before["tables"].items():
            new_rows = after["tables"][table]
            if table == "audit_log":
                if not self._same(new_rows[:len(old_rows)], old_rows):
                    raise ARReceiptError("Owner-billing action altered prior audit history")
                delta = new_rows[len(old_rows):]
                if (Counter((row["action"], row["entity_type"], row["entity_id"]) for row in delta) != Counter(expected_audit)
                        or any(row["actor"] != context["login"] for row in delta)):
                    raise ARReceiptError("Owner-billing action appended an unreviewed audit effect")
                continue
            if table not in added and table not in changed:
                if not self._same(old_rows, new_rows):
                    raise ARReceiptError("Owner-billing action changed unrelated financial or source records")
                continue
            key = "op_id" if table == "idempotency" else "id"
            old, new = ({row[key]: row for row in rows} for rows in (old_rows, new_rows))
            if set(old)-set(new) or set(new)-set(old) != added.get(table, set()):
                raise ARReceiptError("Owner-billing action inserted or removed an unreviewed resource")
            for identifier, old_row in old.items():
                columns = {column for column in old_row if not self._same(old_row[column], new[identifier][column])}
                if not columns <= changed.get(table, {}).get(identifier, set()):
                    raise ARReceiptError("Owner-billing action changed an unreviewed row or field")
            if table == "approvals":
                for identifier in changed.get(table, {}):
                    self._approval_proof(identifier)

    def _terminal_proof(self, action, resource_id, context, before, exc):
        if action not in ("ownerBill.approve", "ownerBill.post", "ownerBill.approveSend", "ownerBill.send"):
            raise ARReceiptError("This owner-billing action cannot commit authorization control writes")
        after = self._snapshot()
        if self._same(before, after):
            raise APRefusal(423 if isinstance(exc, ApprovalExpired) else 412,
                "owner_authorization_expired" if isinstance(exc, ApprovalExpired) else "owner_source_changed",
                "The owner-billing authorization expired. Request fresh review." if isinstance(exc, ApprovalExpired)
                else "The owner-billing source changed. Request fresh review.", "approval")
        approval_id = (self.domain.grant_proof(resource_id)["record"]["approval_id"] if action == "ownerBill.post" else resource_id)
        old = next(row for row in before["tables"]["approvals"] if row["id"] == approval_id)
        current = self._approval_proof(approval_id)["approval"]
        status = "expired" if isinstance(exc, ApprovalExpired) else "invalidated"
        expected_prior = "pending" if action in ("ownerBill.approve", "ownerBill.approveSend") else "granted"
        if old["status"] != expected_prior or current["status"] != status:
            raise ARReceiptError("Owner refusal has no verified original authorization transition")
        if status == "expired":
            if (current["expires_at"] != current["manifest"]["expires_at"] or parse_iso(current["expires_at"]) > utcnow()):
                raise ARReceiptError("Owner refusal cannot invent or shorten an original expiry")
        else:
            changed = False
            try:
                current_manifest = self.cipher._manifest(current["operation"], current["subject_id"], current["actor_role"])
                changed = (material_hash(current_manifest) != current["material_hash"]
                           or not self._same(current_manifest.get("governance"), current["manifest"].get("governance")))
                self.domain.source_proof(current["subject_id"], current=True)
                if action in ("ownerBill.post", "ownerBill.send"):
                    self.domain.require_duty(current["approver"], context["projectId"], "accounting" if action == "ownerBill.post" else "send")
            except (ApprovalError, ReceivableError):
                changed = True
            if not changed:
                raise ARReceiptError("Owner stale refusal lacks an independently changed source or duty")
        source = {"kind": "refusal", "approvalId": approval_id, "billId": current["subject_id"], "status": status,
                  "request": self._request_proof(approval_id), "event": self._event("approval." + status, "approval", approval_id)}
        self._verify_boundary(action, resource_id, context, before, None, source, after=after)
        return source

    def _verify_refusal(self, receipt, source, result):
        action = receipt["fixed_action"]
        if action not in ("ownerBill.approve", "ownerBill.post", "ownerBill.approveSend", "ownerBill.send") or receipt["outcome"] != "refused":
            raise ARReceiptError("Owner refusal is unrelated to a fixed authorization action")
        approval = self._approval_proof(source["approvalId"])["approval"]
        event = self._event_row(source["event"])
        status = source["status"]
        expected = {"code": "owner_authorization_expired" if status == "expired" else "owner_source_changed",
                    "message": "The owner-billing authorization expired. Request fresh review." if status == "expired"
                    else "The owner-billing source changed. Request fresh review.", "target": "approval"}
        if (status not in ("expired", "invalidated") or approval["subject_id"] != source["billId"]
                or receipt["resource_id"] != (source["billId"] if action == "ownerBill.post" else source["approvalId"])
                or event["action"] != "approval." + status or event["entity_type"] != "approval" or event["entity_id"] != source["approvalId"]
                or event["actor"] != receipt["actor_login"] or not self._same(self._request_proof(source["approvalId"]), source["request"])
                or not self._same(result, expected) or receipt["http_status"] != (423 if status == "expired" else 412)):
            raise ARReceiptError("Owner refusal differs from its original audited terminal outcome")

    def integrity_checks(self):
        try:
            self.receipts.verify_integrity()
            for row in self.cipher.db.query("SELECT * FROM ar_action_receipts"):
                self._verify_source(row)
            return {"ok": True, "reason": "Owner-billing receipts retain their original audited effects"}
        except Exception:
            return {"ok": False, "reason": "Owner-billing original action source proof is unavailable"}

    def close_checks(self, period_id):
        result = self.integrity_checks()
        return [] if result["ok"] else [{"kind": "ar_action_receipt", **result}]

    def export(self):
        return {"integrity": self.integrity_checks(), "count": self.cipher.db.scalar("SELECT COUNT(*) FROM ar_action_receipts")}
