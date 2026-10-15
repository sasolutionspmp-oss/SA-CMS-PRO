"""Seven fixed local commercial effects, original proofs and atomic receipts.

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
from .domain.estimates import EstimateError, _optional_text, _text_list, _rate_text, _parse_rate, _content_hash
from .domain.commercial import CommercialError
from .commercial_receipts import CommercialReceipts, CommercialReceiptError, RECEIPT_ACTION, RECEIPT_ENTITY
from .commercial_wire import ACTIONS, CONTRACT_VERSION

LABELS = {"journalCountDelta": 0, "apBalanceDeltaCents": 0, "providerCallsDelta": 0}
_TABLES = {"estimates", "estimate_lines", "approvals", "idempotency", "commitments", "sov_lines",
           "commercial_estimate_sources", "commercial_line_sources", "commercial_handoffs", "commercial_commitment_sources",
           "commercial_action_receipts"}


class CommercialActionRunner:
    def __init__(self, cipher, contract, preflight):
        if contract.cipher is not cipher or preflight.cipher is not cipher or preflight.contract is not contract:
            raise ValueError("Commercial actions require one owned scoped runtime")
        self.cipher, self.contract, self.preflight = cipher, contract, preflight
        self.domain = cipher.plugin("commercial")
        self.receipts = CommercialReceipts(cipher.db, cipher.audit)

    @contextmanager
    def _transaction(self):
        with self.cipher.db.transaction() as conn:
            name = new_id("commercial_api")
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
        if action not in ACTIONS or type(resource_id) is not str or not resource_id or len(resource_id) > 160:
            raise APRefusal(422, "invalid_action", "Choose a supported commercial action.", "action")
        try:
            normalized = str(UUID(key)) if type(key) is str and len(key) == 36 else None
        except (ValueError, AttributeError):
            normalized = None
        if normalized is None or normalized != key.casefold():
            raise APRefusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.", "Repeatability-Request-ID")
        if type(if_match) is not str or not if_match or len(if_match) > 256:
            raise APRefusal(422, "missing_record_version", "Supply the commercial version reviewed for this action.", "If-Match")
        typed = self.preflight._body(action, body, effect=True)
        fingerprint = body.get("fingerprint")
        if type(fingerprint) is not str or not fingerprint or not fingerprint.isascii() or len(fingerprint) > 256:
            raise APRefusal(422, "invalid_fingerprint", "Supply the original commercial review fingerprint.", "fingerprint")
        return normalized, {"contractVersion": CONTRACT_VERSION, "fixedAction": action, "resourceId": resource_id,
                            "canonicalTypedBody": {**typed, "fingerprint": fingerprint}, "originalIfMatch": if_match,
                            "preflightFingerprint": fingerprint}

    def _namespace(self, person_id, key, action, binding):
        # Future same-workspace composition must not steal an existing AP key or
        # pending worker reservation. These calls are metadata-only and follow
        # current commercial authorization. The dedicated server seeds none.
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
                    raise PermissionError("Commercial practice effects require disposable memory")
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
                    verified = self.preflight.verify(person_id, action, resource_id, body, if_match)
                    if any(verified[key] != context[key] for key in ("personId", "login", "duty", "projectId")):
                        raise CommercialReceiptError("Commercial authority changed within the locked review")
                    # Freeze mutable prospective facts before an effect callback
                    # can attempt to change its own expected plan.
                    reviewed = loads(canonical_json({key: verified[key] for key in ("personId", "login", "duty", "projectId", "typed", "plan", "sourceFacts", "manifest", "review")}))
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
                        result = {"code": "acceptance_expired" if status == 423 else "commercial_source_changed",
                                  "message": "The estimator authorization expired. Request fresh review." if status == 423
                                  else "The commercial source changed. Request fresh review.", "target": "approval"}
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
            raise APRefusal(403, "action_not_authorized", "Your current project duties do not permit this commercial action.") from None
        except (ApprovalError, EstimateError, CommercialError):
            raise APRefusal(409, "action_refused", "This commercial action cannot proceed. Refresh its review.") from None
        except Exception:
            raise APRefusal(500, "action_unavailable", "The action did not complete. Retry the same reviewed request.") from None
        if deferred:
            raise deferred
        if response is None:
            raise APRefusal(500, "action_unavailable", "The action did not complete. Retry the same reviewed request.")
        return response

    def _record(self, context, key, action, resource_id, binding, result, source, *, outcome="success", http_status=200):
        """Prove the callback stored the exact authorized invocation and outcome."""
        arguments = {"person_id": context["personId"], "actor_login": context["login"], "repeatability_uuid": key,
                     "action": action, "resource_id": resource_id, "binding": binding, "result": result, "source": source,
                     "outcome": outcome, "http_status": http_status}
        expected = loads(canonical_json(arguments))
        workspace = self.cipher.db.mode_status()["workspace_id"]
        returned = self.receipts.record(**arguments)
        stored = self.cipher.db.one("SELECT * FROM commercial_action_receipts WHERE id=?", (returned["id"],))
        fields = {"workspace_id": workspace, "canonical_person_id": expected["person_id"], "actor_login": expected["actor_login"],
                  "repeatability_uuid": expected["repeatability_uuid"], "contract_version": CONTRACT_VERSION,
                  "fixed_action": expected["action"], "resource_id": expected["resource_id"],
                  "binding_json": canonical_json(expected["binding"]), "result_json": canonical_json(expected["result"]),
                  "source_json": canonical_json(expected["source"]), "outcome": expected["outcome"], "http_status": expected["http_status"]}
        if (stored is None or canonical_json(stored) != canonical_json(returned)
                or canonical_json(arguments) != canonical_json(expected)
                or any(canonical_json(stored[field]) != canonical_json(value) for field, value in fields.items())):
            raise CommercialReceiptError("Commercial receipt changed its exact original reviewed invocation")
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
            raise CommercialReceiptError("Commercial effect requires one original audited event")
        return {"auditSeq": rows[0]["seq"], "auditHash": rows[0]["entry_hash"]}

    def _event_row(self, ref, *, with_actor=False):
        fields = {"auditSeq", "auditHash", "actor"} if with_actor else {"auditSeq", "auditHash"}
        if (type(ref) is not dict or set(ref) != fields
                or type(ref["auditSeq"]) is not int or ref["auditSeq"] <= 0
                or type(ref["auditHash"]) is not str):
            raise CommercialReceiptError("Commercial original effect requires its exact integer audit reference")
        row = self.cipher.db.one("SELECT * FROM audit_log WHERE seq=?", (ref["auditSeq"],))
        if (row is None or row["entry_hash"] != ref["auditHash"]
                or with_actor and (type(ref["actor"]) is not str or row["actor"] != ref["actor"])):
            raise CommercialReceiptError("Commercial original effect event disappeared")
        return row

    def _apply(self, action, resource_id, context):
        actor, typed = context["login"], context["typed"]
        if action in ("estimate.create", "estimate.revise"):
            source = (self.domain.create(resource_id, typed, actor=actor) if action == "estimate.create"
                      else self.domain.revise(resource_id, typed, actor=actor))
            proof = {"kind": "creation", "estimateId": source["estimateId"], "record": source["record"], "lines": source["lines"]}
        elif action == "estimate.request":
            self.cipher.check_estimate_request(resource_id, requested_by=actor, actor_role="estimator")
            approval = self.cipher.request_approval("estimate.approve", resource_id, actor_role="estimator", requested_by=actor)
            proof = {"kind": "request", "estimateId": resource_id, "approvalId": approval["id"],
                     "request": self.cipher.estimates.estimate_approval_proof(approval["id"])}
        elif action in ("estimate.accept", "estimate.apply"):
            approval = self.cipher.approvals.get(resource_id)
            name = new_id("commercial_service")
            conn = self.cipher.db.conn
            conn.execute(f"SAVEPOINT {name}")
            service_before = self._snapshot()
            try:
                if action == "estimate.accept":
                    self.cipher.check_estimate_grant(resource_id, approver=actor, approver_role="estimator")
                    self.cipher.approve(resource_id, approver=actor, approver_role="estimator")
                else:
                    self.cipher.check_estimate_application(resource_id, actor=actor)
                    self.cipher.execute(resource_id, actor=actor)
            except (StaleApprovalError, ApprovalExpired) as exc:
                if self._snapshot() == service_before:
                    raise self.preflight._refusal(exc, "approval") from None
                try:
                    self._terminal_proof(action, resource_id, context, service_before, exc)
                except BaseException:
                    if conn.in_transaction:
                        conn.execute(f"ROLLBACK TO {name}")
                    raise
                raise
            except BaseException:
                if conn.in_transaction:
                    conn.execute(f"ROLLBACK TO {name}")
                raise
            finally:
                if conn.in_transaction:
                    conn.execute(f"RELEASE {name}")
            proof = {"kind": "grant" if action == "estimate.accept" else "acceptance", "approvalId": resource_id,
                     "estimateId": approval["subject_id"], "request": self.cipher.estimates.estimate_approval_proof(resource_id),
                     "event": self._event("approval.granted" if action == "estimate.accept" else "estimate.approved",
                                          "approval" if action == "estimate.accept" else "estimate", resource_id if action == "estimate.accept" else approval["subject_id"])}
            if action == "estimate.apply":
                proof["commandId"] = f"exec:{resource_id}"
                proof["acceptance"] = self.cipher.estimates.estimate_proof(approval["subject_id"], accepted=True)["acceptance"]
        elif action == "estimate.prepareHandoff":
            handoff = self.domain.prepare_handoff(resource_id, context["plan"]["package"]["id"], actor=actor)
            proof = {"kind": "handoff", "handoffId": handoff["handoffId"], "estimateId": resource_id, "record": handoff["record"]}
        else:
            commitment = self.domain.create_commitment(resource_id, actor=actor)
            proof = {"kind": "commitment", "commitmentId": commitment["commitmentId"], "handoffId": resource_id,
                     "estimateId": commitment["handoff"]["source"]["estimateId"], "record": commitment["record"]}
        return self._expected_result(action, proof), proof

    def _expected_result(self, action, source):
        result = {"action": action, **LABELS}
        if action in ("estimate.create", "estimate.revise"):
            baseline = source["record"]["baseline"]
            result.update(status="draft", estimateId=source["estimateId"], revision=baseline["revision"], totalCents=int(money(baseline["total"])*100))
            if action == "estimate.revise":
                result["predecessorId"] = self.cipher.db.scalar("SELECT supersedes FROM estimates WHERE id=?", (source["estimateId"],))
        elif action in ("estimate.request", "estimate.accept", "estimate.apply"):
            result.update(status={"estimate.request": "pending", "estimate.accept": "granted", "estimate.apply": "approved"}[action],
                          approvalId=source["approvalId"], estimateId=source["estimateId"])
            if action == "estimate.apply":
                baseline = self.cipher.estimates.estimate_proof(source["estimateId"], accepted=True)
                result.update(revision=baseline["revision"], totalCents=int(money(baseline["total"])*100))
        elif action == "estimate.prepareHandoff":
            result.update(status="prepared", handoffId=source["handoffId"], estimateId=source["estimateId"], totalCents=int(money(source["record"]["snapshot"]["total"])*100))
        else:
            result.update(status="draft", commitmentId=source["commitmentId"], handoffId=source["handoffId"], estimateId=source["estimateId"],
                          totalCents=int(money(source["record"]["commitment"]["original_amount"])*100))
        return result

    def _verify_input(self, action, resource_id, typed, source):
        revised = action == "estimate.revise"
        engine, facts, basis = self.domain._input(typed, revised=revised)
        normalized = self.cipher.estimates._normalize_lines(engine)
        baseline, record = source["baseline"], source["record"]
        actual = [{key: line[key] for key in ("line_no", "description", "quantity", "unit", "unit_price", "amount")} for line in baseline["lines"]]
        scope = {"price_book_ref": _optional_text("price_book_ref", typed["priceBookRef"], empty_is_none=False),
                 "inclusions": _text_list("inclusions", typed["inclusions"]), "exclusions": _text_list("exclusions", typed["exclusions"]),
                 "measurement_basis": _optional_text("measurement_basis", basis, empty_is_none=True)}
        predecessor = self.cipher.db.scalar("SELECT supersedes FROM estimates WHERE id=?", (source["estimateId"],))
        expected_hash = _content_hash(project_id=source["projectId"], document_revision_id=typed["documentRevisionId"],
            document_hash=source["drawing"]["contentHash"], lines=normalized, **scope,
            contingency_rate=_rate_text(_parse_rate(typed["contingencyRate"])), subtotal=baseline["subtotal"],
            contingency=baseline["contingency"], total_=baseline["total"], supersedes=resource_id if revised else None)
        if (canonical_json(actual) != canonical_json(normalized) or canonical_json(baseline["scope"]) != canonical_json(scope) or record["document_revision_id"] != typed["documentRevisionId"]
                or baseline["contentHash"] != expected_hash or predecessor != (resource_id if revised else None)
                or (not revised and source["projectId"] != resource_id) or len(facts) != len(source["lines"])):
            raise CommercialReceiptError("Original estimate differs from its exact typed quantities, rates or declared scope")
        for fact, line in zip(facts, source["lines"]):
            if any(line[key] != fact[key] for key in ("source_locator", "cost_code", "method", "verified_geometry", "measurement_basis", "previous_line_id")):
                raise CommercialReceiptError("Original manual estimate differs from its typed source/lineage facts")
        if revised:
            creation = self._event_row(baseline["creation"], with_actor=True)
            if loads(creation["payload_json"])["removed_exclusions"] != _text_list("removed_exclusions", typed["removedExclusions"]):
                raise CommercialReceiptError("Original revision differs from its declared removed exclusions")

    def _verify_plan(self, action, resource_id, context, plan, source):
        actor = context["login"]
        if action in ("estimate.create", "estimate.revise"):
            original = self.domain.source(source["estimateId"])
            self._verify_input(action, resource_id, context["typed"], original)
            baseline = original["baseline"]
            expected = plan["estimatePlan"]
            if (baseline["contentHash"] != expected["content_hash"] or baseline["revision"] != expected["revision"]
                    or any(baseline[key] != expected[key] for key in ("subtotal", "contingency", "total"))
                    or canonical_json(original["record"]["project"]) != canonical_json(plan["project"]) or canonical_json(original["drawing"]) != canonical_json(plan["drawing"])
                    or original["record"]["previous_source_hash"] != plan["previousSourceHash"]
                    or original["record"]["created_by"] != actor):
                raise CommercialReceiptError("Created revision differs from its full reviewed domain plan")
            for actual, fact in zip(original["lines"], plan["manualFacts"]):
                if any(actual[key] != fact[key] for key in ("source_locator", "cost_code", "method", "verified_geometry", "measurement_basis", "previous_line_id")):
                    raise CommercialReceiptError("Created manual facts differ from their full reviewed plan")
                if fact["stable_line_id"] is not None and actual["stable_line_id"] != fact["stable_line_id"]:
                    raise CommercialReceiptError("Revision changed its reviewed stable line correspondence")
        elif action == "estimate.request":
            approval = self.cipher.approvals.get(source["approvalId"])
            if (approval["material_hash"] != material_hash(context["manifest"])
                    or canonical_json(approval["manifest"].get("governance")) != canonical_json(context["manifest"].get("governance"))
                    or approval["requested_by"] != actor):
                raise CommercialReceiptError("Requested acceptance differs from its reviewed material/governance")
        elif action in ("estimate.accept", "estimate.apply"):
            approval = self.cipher.approvals.get(resource_id)
            original = context["sourceFacts"]["approval"]
            if any(approval[key] != original[key] for key in ("manifest_hash", "material_hash", "nonce", "expires_at")):
                raise CommercialReceiptError("Estimator decision changed the reviewed original authorization")
            baseline = self.cipher.estimates.estimate_proof(source["estimateId"], accepted=action == "estimate.apply")
            if any(baseline[key] != plan[old] for key, old in (("contentHash", "content_hash"), ("subtotal", "subtotal"), ("contingency", "contingency"), ("total", "total"))):
                raise CommercialReceiptError("Estimator decision changed the reviewed baseline")
        elif action == "estimate.prepareHandoff":
            if canonical_json(source["record"]["snapshot"]) != canonical_json(plan) or source["record"]["created_by"] != actor:
                raise CommercialReceiptError("Prepared handoff differs from the full reviewed snapshot")
        else:
            record = source["record"]
            if (record["created_by"] != actor or record["handoff_hash"] != hash_json(plan["handoff"]["record"])
                    or any(record["commitment"][key] != plan[key] for key in ("project_id", "supplier_id", "estimate_id", "title", "retainage_rate"))
                    or record["commitment"]["original_amount"] != plan["total"]
                    or canonical_json([{key: row[key] for key in ("description", "cost_code", "amount")} for row in record["sov"]]) != canonical_json(plan["sov_lines"])):
                raise CommercialReceiptError("Created subcontract differs from the full reviewed handoff plan")

    def _verify_source(self, receipt):
        source, result, binding = (loads(receipt[key]) for key in ("source_json", "result_json", "binding_json"))
        action, resource_id, actor = receipt["fixed_action"], receipt["resource_id"], receipt["actor_login"]
        typed = self.preflight._body(action, binding["canonicalTypedBody"], effect=True)
        if source["kind"] == "refusal":
            if action not in ("estimate.accept", "estimate.apply") or source["approvalId"] != resource_id or receipt["outcome"] != "refused":
                raise CommercialReceiptError("Commercial refusal has an unrelated source")
            self.cipher.estimates.estimate_approval_proof(resource_id)
            approval = self.cipher.approvals.get(resource_id)
            event = self._event_row(source["event"])
            status = source["status"]
            expected = {"code": "acceptance_expired" if status == "expired" else "commercial_source_changed",
                        "message": "The estimator authorization expired. Request fresh review." if status == "expired"
                        else "The commercial source changed. Request fresh review.", "target": "approval"}
            if (status not in ("expired", "invalidated") or approval["status"] != status or event["actor"] != actor
                    or event["action"] != f"approval.{status}" or event["entity_id"] != resource_id
                    or canonical_json(result) != canonical_json(expected) or receipt["http_status"] != (423 if status == "expired" else 412)):
                raise CommercialReceiptError("Commercial refusal differs from its original terminal control")
            return
        if receipt["outcome"] != "success" or receipt["http_status"] != 200:
            raise CommercialReceiptError("Successful commercial source has a false outcome")
        if action in ("estimate.create", "estimate.revise"):
            current = self.domain.source(source["estimateId"])
            if source["kind"] != "creation" or canonical_json(current["record"]) != canonical_json(source["record"]) or canonical_json(current["lines"]) != canonical_json(source["lines"]) or current["record"]["created_by"] != actor:
                raise CommercialReceiptError("Estimate receipt lost its original immutable manual source")
            self._verify_input(action, resource_id, typed, current)
        elif action in ("estimate.request", "estimate.accept", "estimate.apply"):
            approval_id = source["approvalId"]
            approval = self.cipher.approvals.get(approval_id)
            if (approval["operation"] != "estimate.approve" or approval["actor_role"] != "estimator"
                    or approval["subject_id"] != source["estimateId"]
                    or canonical_json(self.cipher.estimates.estimate_approval_proof(approval_id)) != canonical_json(source["request"])):
                raise CommercialReceiptError("Commercial acceptance receipt lost its original fixed request")
            self.domain.source(source["estimateId"])
            if action == "estimate.request":
                if source["kind"] != "request" or source["estimateId"] != resource_id or approval["requested_by"] != actor:
                    raise CommercialReceiptError("Commercial request has unrelated original attribution")
            else:
                event = self._event_row(source["event"])
                expected_action = "approval.granted" if action == "estimate.accept" else "estimate.approved"
                if approval_id != resource_id or event["action"] != expected_action or event["actor"] != actor:
                    raise CommercialReceiptError("Commercial decision has unrelated original attribution")
                if action == "estimate.accept":
                    if source["kind"] != "grant" or approval["approver"] != actor or event["entity_id"] != approval_id:
                        raise CommercialReceiptError("Commercial grant differs from its original reviewer")
                else:
                    baseline = self.cipher.estimates.estimate_proof(source["estimateId"], accepted=True)
                    if source["kind"] != "acceptance" or canonical_json(baseline["acceptance"]) != canonical_json(source["acceptance"]) or approval["consumed_by"] != actor:
                        raise CommercialReceiptError("Commercial acceptance differs from its original consumed grant")
                    self._verify_command(source, actor)
        elif action == "estimate.prepareHandoff":
            handoff = self.domain.handoff(source["handoffId"])
            if source["kind"] != "handoff" or source["estimateId"] != resource_id or canonical_json(handoff["record"]) != canonical_json(source["record"]) or source["record"]["created_by"] != actor:
                raise CommercialReceiptError("Commercial receipt lost its original handoff")
        else:
            commitment = self.domain.commitment_proof(source["commitmentId"])
            if (source["kind"] != "commitment" or source["handoffId"] != resource_id or canonical_json(commitment["record"]) != canonical_json(source["record"])
                    or commitment["handoff"]["source"]["estimateId"] != source["estimateId"] or source["record"]["created_by"] != actor):
                raise CommercialReceiptError("Commercial receipt lost its original subcontract correspondence")
        if canonical_json(result) != canonical_json(self._expected_result(action, source)):
            raise CommercialReceiptError("Commercial result differs from the exact original observed effect")

    def _verify_command(self, source, actor):
        payload = {"approval_id": source["approvalId"], "operation": "estimate.approve", "subject_id": source["estimateId"]}
        row = self.cipher.db.one("SELECT * FROM idempotency WHERE op_id=?", (source["commandId"],))
        event = self._event_row(self._event("command.executed", "command", source["commandId"]))
        expected = {"estimate": source["estimateId"], "status": "approved"}
        if (row is None or row["payload_hash"] != hash_json(payload) or row["result_json"] != canonical_json(expected)
                or event["actor"] != actor or loads(event["payload_json"]) != {"payload_hash": hash_json(payload)}):
            raise CommercialReceiptError("Acceptance command lost its exact original payload/result proof")

    def _snapshot(self):
        names = self.cipher.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return {"schema": self.cipher.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"),
                "tables": {row["name"]: self.cipher.db.query('SELECT * FROM "' + row["name"].replace('"', '""') + '"') for row in names}}

    def _verify_boundary(self, action, resource_id, context, before, receipt, source, *, after=None):
        after = self._snapshot() if after is None else after
        if before["schema"] != after["schema"] or before["tables"].keys() != after["tables"].keys():
            raise CommercialReceiptError("Commercial action changed the workspace schema")
        added, changed, events = {}, {}, []
        if receipt is not None:
            added["commercial_action_receipts"] = {receipt["id"]}
            events.append((RECEIPT_ACTION, RECEIPT_ENTITY, receipt["id"]))
        if source["kind"] == "refusal":
            changed["approvals"] = {resource_id: {"status", "invalidated_reason"}}
            events.append((f"approval.{source['status']}", "approval", resource_id))
        elif action in ("estimate.create", "estimate.revise"):
            estimate_id = source["estimateId"]
            added.update(estimates={estimate_id}, estimate_lines={line["estimate_line_id"] for line in source["lines"]},
                         commercial_estimate_sources={source["record"]["id"]}, commercial_line_sources={line["id"] for line in source["lines"]})
            events += [("estimate.created", "estimate", estimate_id), ("commercial.estimate_sources_recorded", "commercial_estimate_sources", source["record"]["id"])]
            events += [("commercial.line_sources_recorded", "commercial_line_sources", line["id"]) for line in source["lines"]]
            if action == "estimate.revise":
                changed["estimates"] = {resource_id: {"status"}}
                events.append(("estimate.superseded", "estimate", resource_id))
                targets = [row["id"] for row in before["tables"]["approvals"] if row["subject_type"] == "estimate" and row["subject_id"] == resource_id and row["status"] in ("pending", "granted")]
                changed["approvals"] = {identifier: {"status", "invalidated_reason"} for identifier in targets}
                events += [("approval.invalidated", "approval", identifier) for identifier in targets]
        elif action == "estimate.request":
            added["approvals"] = {source["approvalId"]}
            events.append(("approval.requested", "approval", source["approvalId"]))
        elif action == "estimate.accept":
            changed["approvals"] = {resource_id: {"status", "approver", "granted_at"}}
            events.append(("approval.granted", "approval", resource_id))
        elif action == "estimate.apply":
            added["idempotency"] = {source["commandId"]}
            changed["estimates"] = {source["estimateId"]: {"status", "approval_id"}}
            targets = [row["id"] for row in before["tables"]["approvals"] if row["id"] != resource_id and row["subject_type"] == "estimate" and row["subject_id"] == source["estimateId"] and row["status"] in ("pending", "granted")]
            changed["approvals"] = {identifier: {"status", "invalidated_reason"} for identifier in targets}
            changed["approvals"][resource_id] = {"status", "consumed_by", "consumed_at"}
            events += [("approval.invalidated", "approval", identifier) for identifier in targets]
            events += [("approval.consumed", "approval", resource_id), ("estimate.approved", "estimate", source["estimateId"]), ("command.executed", "command", source["commandId"])]
        elif action == "estimate.prepareHandoff":
            added["commercial_handoffs"] = {source["handoffId"]}
            events.append(("commercial.handoffs_recorded", "commercial_handoffs", source["handoffId"]))
        else:
            added.update(commitments={source["commitmentId"]}, sov_lines={line["id"] for line in source["record"]["sov"]}, commercial_commitment_sources={source["record"]["id"]})
            events += [("commitment.created", "commitment", source["commitmentId"]), ("commercial.commitment_sources_recorded", "commercial_commitment_sources", source["record"]["id"])]
        for table, old_rows in before["tables"].items():
            new_rows = after["tables"][table]
            if table == "audit_log":
                if new_rows[:len(old_rows)] != old_rows:
                    raise CommercialReceiptError("Commercial action altered previous audit history")
                delta = new_rows[len(old_rows):]
                if (Counter((row["action"], row["entity_type"], row["entity_id"]) for row in delta) != Counter(events)
                        or any(row["actor"] != context["login"] for row in delta)):
                    raise CommercialReceiptError("Commercial action appended unrelated audit effects")
                continue
            if table not in added and table not in changed:
                if old_rows != new_rows:
                    raise CommercialReceiptError("Commercial action changed unrelated records or financial state")
                continue
            key = "op_id" if table == "idempotency" else "id"
            old, new = ({row[key]: row for row in rows} for rows in (old_rows, new_rows))
            if set(old)-set(new) or set(new)-set(old) != added.get(table, set()):
                raise CommercialReceiptError("Commercial action inserted or removed an unreviewed resource")
            for identifier, row in old.items():
                columns = {column for column in row if row[column] != new[identifier][column]}
                if not columns <= changed.get(table, {}).get(identifier, set()):
                    raise CommercialReceiptError("Commercial action changed an unreviewed row or field")
            if table == "approvals":
                for identifier in changed.get(table, {}):
                    self.cipher.estimates.estimate_approval_proof(identifier)
                    if identifier != resource_id or source["kind"] == "refusal":
                        if new[identifier]["status"] not in ("invalidated", "expired"):
                            raise CommercialReceiptError("Commercial action did not apply its declared control transition")

    def _terminal_proof(self, action, resource_id, context, before, exc):
        if action not in ("estimate.accept", "estimate.apply"):
            raise CommercialReceiptError("This local action cannot commit terminal acceptance bookkeeping")
        after = self._snapshot()
        old = next(row for row in before["tables"]["approvals"] if row["id"] == resource_id)
        current = self.cipher.approvals.get(resource_id)
        status = "expired" if isinstance(exc, ApprovalExpired) else "invalidated"
        if old["status"] != ("pending" if action == "estimate.accept" else "granted") or current["status"] != status:
            raise CommercialReceiptError("Terminal refusal has no verified original control transition")
        if status == "expired":
            if parse_iso(current["expires_at"]) > utcnow():
                raise CommercialReceiptError("An unexpired acceptance cannot commit an expiry refusal")
        else:
            changed = False
            try:
                manifest = self.cipher._manifest("estimate.approve", current["subject_id"], "estimator")
                changed = (material_hash(manifest) != current["material_hash"] or manifest.get("governance") != current["manifest"].get("governance"))
                self.cipher.estimates.acceptance_preflight(current["subject_id"])
            except EstimateError:
                changed = True
            if not changed:
                raise CommercialReceiptError("Stale refusal lacks independently changed source/material/governance")
        source = {"kind": "refusal", "approvalId": resource_id, "status": status,
                  "event": self._event(f"approval.{status}", "approval", resource_id)}
        self._verify_boundary(action, resource_id, context, before, None, source, after=after)
        return source

    def integrity_checks(self):
        try:
            self.receipts.verify_integrity()
            for row in self.cipher.db.query("SELECT * FROM commercial_action_receipts"):
                self._verify_source(row)
            return {"ok": True, "reason": "Commercial receipts retain their original audited effects"}
        except Exception:
            return {"ok": False, "reason": "Commercial receipt source proof is unavailable"}

    def close_checks(self, period_id):
        result = self.integrity_checks()
        return [] if result["ok"] else [{"kind": "commercial_action_receipt", **result}]

    def export(self):
        return {"integrity": self.integrity_checks(), "count": self.cipher.db.scalar("SELECT COUNT(*) FROM commercial_action_receipts")}
