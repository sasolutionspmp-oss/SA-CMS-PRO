"""Nine fixed local RFI effects with original proofs and atomic receipts."""
from collections import Counter
from contextlib import contextmanager
from uuid import UUID

from .ap_contract import APRefusal
from .core.api_receipts import APIRepeatabilityConflict
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow
from .domain.rfi_controls import RESPONSE, DISTRIBUTE, SOURCE_KIND
from .domain.drawing_sources import issued_drawing_proof
from .domain.owned_sources import owned_revision_proof, document_rights_proof
from .rfi_receipts import (RFIReceipts, RFIReceiptError, RECEIPT_ACTION, RECEIPT_ENTITY,
                               require_other_namespaces)
from .rfi_wire import ACTIONS, CONTRACT_VERSION

LABELS = {"journalDelta": 0, "changeDraftDelta": 0, "changeExecutionDelta": 0,
          "commitmentDelta": 0, "contractValueDeltaCents": 0, "budgetDeltaCents": 0,
          "scheduleBaselineDeltaDays": 0, "externalDistribution": False,
          "engineeringCertification": False, "adoptsPotentialImpacts": False, "mailSinkOnly": True}


class RFIActionRunner:
    def __init__(self, cipher, contract, preflight):
        if contract.cipher is not cipher or preflight.cipher is not cipher or preflight.contract is not contract:
            raise ValueError("RFI actions require one owned scoped runtime")
        self.cipher, self.contract, self.preflight = cipher, contract, preflight
        self.domain = cipher.plugin("rfi_controls")
        self.receipts = RFIReceipts(cipher.db, cipher.audit)

    @staticmethod
    def _same(left, right):
        return canonical_json(left) == canonical_json(right)

    @contextmanager
    def _transaction(self):
        with self.cipher.db.transaction() as conn:
            name = new_id("rfi_api")
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
            raise APRefusal(422, "invalid_action", "Choose a supported rfi action.", "action")
        try:
            normalized = str(UUID(key)) if type(key) is str and len(key) == 36 else None
        except (ValueError, AttributeError):
            normalized = None
        if normalized is None or normalized != key.casefold():
            raise APRefusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.", "Repeatability-Request-ID")
        if type(if_match) is not str or not if_match or len(if_match) > 256:
            raise APRefusal(422, "missing_record_version", "Supply the rfi version reviewed for this action.", "If-Match")
        typed = self.preflight._body(action, body, effect=True)
        fingerprint = body.get("fingerprint")
        if type(fingerprint) is not str or not fingerprint or not fingerprint.isascii() or len(fingerprint) > 256:
            raise APRefusal(422, "invalid_fingerprint", "Supply the original rfi review fingerprint.", "fingerprint")
        return normalized, {"contractVersion": CONTRACT_VERSION, "fixedAction": action, "resourceId": resource_id,
            "canonicalTypedBody": {**typed, "fingerprint": fingerprint}, "originalIfMatch": if_match, "preflightFingerprint": fingerprint}

    def run(self, person_id, action, resource_id, body, *, repeatability_key, if_match):
        key, binding = self._shape(action, resource_id, body, repeatability_key, if_match)
        response, deferred = None, None
        try:
            with self._transaction():
                self.cipher.db.require_practice_mode()
                self.cipher.db.require_write_authority()
                if not self.cipher.db.in_memory:
                    raise PermissionError("RFI practice effects require disposable memory")
                context = self.contract.authorize(person_id, action, resource_id)
                require_other_namespaces(self.cipher.db, self.cipher.audit, context["personId"], key, action, binding)
                receipt = self.receipts.find(context["personId"], key)
                if receipt is not None:
                    if receipt["binding_json"] != canonical_json(binding):
                        raise APIRepeatabilityConflict("This key belongs to a different original rfi request")
                    self._verify_source(receipt)
                    if receipt["outcome"] == "refused":
                        deferred = self._stored_refusal(receipt, replayed=True)
                    else:
                        response = self._response(receipt, replayed=True)
                else:
                    review_started = utcnow()
                    checked = self.preflight.verify(person_id, action, resource_id, body, if_match)
                    keys = ("personId", "login", "duty", "operationRole", "projectId")
                    if any(not self._same(context[k], checked[k]) for k in keys):
                        raise RFIReceiptError("RFI authority changed within the locked review")
                    reviewed = loads(canonical_json({k: checked[k] for k in (*keys, "typed", "plan", "sourceFacts", "manifest", "review")}))
                    reviewed["reviewClockStartedAt"] = review_started.isoformat()
                    before = self._snapshot()
                    try:
                        result, source = self._apply(action, resource_id, checked)
                        self._verify_plan(action, resource_id, reviewed, source)
                        source["reviewedPlanHash"] = hash_json(reviewed["plan"])
                        source["reviewedSourceHash"] = hash_json(reviewed["sourceFacts"])
                    except (ApprovalExpired, StaleApprovalError) as exc:
                        source = self._terminal_proof(action, resource_id, context, before, exc)
                        result = self._refusal_result(source["status"])
                        receipt = self._record(context, key, action, resource_id, binding, result, source, outcome="refused",
                                               http_status=423 if source["status"] == "expired" else 412)
                        self._verify_source(receipt)
                        self._verify_boundary(action, context, before, receipt, source)
                        deferred = self._stored_refusal(receipt, replayed=False)
                    else:
                        receipt = self._record(context, key, action, resource_id, binding, result, source)
                        self._verify_source(receipt)
                        self._verify_boundary(action, context, before, receipt, source)
                        response = self._response(receipt, replayed=False)
        except APRefusal:
            raise
        except APIRepeatabilityConflict:
            raise APRefusal(409, "repeatability_conflict", "This key belongs to a different original reviewed request.") from None
        except PermissionError:
            raise APRefusal(403, "action_not_authorized", "Your current project duties do not permit this rfi action.") from None
        except ApprovalError:
            raise APRefusal(409, "action_refused", "This rfi action cannot proceed. Refresh its review.") from None
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
        stored = self.cipher.db.one("SELECT * FROM rfi_action_receipts WHERE id=?", (returned["id"],))
        fields = {"workspace_id": workspace, "canonical_person_id": expected["person_id"], "actor_login": expected["actor_login"],
                  "repeatability_uuid": expected["repeatability_uuid"], "contract_version": CONTRACT_VERSION,
                  "fixed_action": expected["action"], "resource_id": expected["resource_id"],
                  "binding_json": canonical_json(expected["binding"]), "result_json": canonical_json(expected["result"]),
                  "source_json": canonical_json(expected["source"]), "outcome": expected["outcome"], "http_status": expected["http_status"]}
        if (stored is None or not self._same(stored, returned) or not self._same(arguments, expected)
                or any(not self._same(stored[field], value) for field, value in fields.items())):
            raise RFIReceiptError("RFI receipt changed its exact original reviewed invocation")
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

    def _source_original(self, rfi_id):
        proof = self.domain.source_proof(rfi_id)
        return {"record": proof["record"], "sourceHash": proof["sourceHash"]}

    def _request_original(self, approval_id):
        proof = self.domain.approval_proof(approval_id)
        row = proof["record"]
        return {"source": proof["source"], "request": proof["request"],
                "original": {key: row[key] for key in ("id", "operation", "subject_type", "subject_id", "actor_role", "policy_version",
                    "manifest", "manifest_hash", "material_hash", "nonce", "expires_at", "requested_by", "requested_at")}}

    @staticmethod
    def _operation(action):
        return DISTRIBUTE if action in ("rfi.requestDistribution", "rfi.approveDistribution", "rfi.distribute") else RESPONSE

    def _apply(self, action, resource_id, context):
        actor, typed = context["login"], context["typed"]
        source = {"kind": action.split(".")[1]}
        if action == "rfi.create":
            effect = self.domain.create(resource_id, typed, actor=actor)
            rid = effect["id"]
        elif action in ("rfi.draftResponse", "rfi.setDistribution"):
            method = self.domain.draft_response if action == "rfi.draftResponse" else self.domain.set_distribution_list
            method(resource_id, typed, actor=actor)
            rid = resource_id
            proof = self.domain.source_proof(rid)
            source["revision"] = proof["latestResponse" if action == "rfi.draftResponse" else "latestDistribution"]
        elif action in ("rfi.requestResponse", "rfi.requestDistribution"):
            effect = self.cipher.request_approval(self._operation(action), resource_id, actor_role="pm", requested_by=actor)
            source["approvalId"] = effect["id"]
            rid = resource_id
        else:
            source["approvalId"] = resource_id
            if action in ("rfi.approveResponse", "rfi.approveDistribution"):
                self.cipher.approve(resource_id, approver=actor, approver_role="pm")
                source["grant"] = self.domain.approval_proof(resource_id)["grant"]
            else:
                effect = self.cipher.execute(resource_id, actor=actor)
                source["effect"] = self.domain.effect_proof(resource_id)
                source["commandId"] = "exec:" + resource_id
                native = source["effect"]["result"] if action == "rfi.applyResponse" else self._distribution_result(source["effect"]["record"])
                if not self._same(effect.result, native):
                    raise RFIReceiptError("RFI command returned an outcome different from its original effect")
            rid = self.domain.approval_proof(resource_id)["record"]["subject_id"]
        source.update(rfiId=rid, **self._source_original(rid))
        if "approvalId" in source:
            source["request"] = self._request_original(source["approvalId"])
        return self._expected_result(action, source), source

    @staticmethod
    def _distribution_result(record):
        result = {key: value for key, value in record.items() if key != "recipients_json"}
        result["recipients"] = loads(record["recipients_json"])
        return result

    def _expected_result(self, action, source):
        result = {"action": action, "rfiId": source["rfiId"], **LABELS}
        if action == "rfi.create":
            result.update(status="open", rfiVersion=1)
        elif action in ("rfi.draftResponse", "rfi.setDistribution"):
            record = source["revision"]["record"]
            result.update(status="draft" if action == "rfi.draftResponse" else "recorded",
                          rfiStatus="open" if action == "rfi.draftResponse" else "answered", rfiVersion=record["native_version"])
            result["responseRevisionId" if action == "rfi.draftResponse" else "distributionRevisionId"] = record["id"]
        else:
            sealed = source["request"]["source"]["record"]
            result.update(approvalId=source["approvalId"], rfiVersion=sealed["context"]["nativeVersion"])
            if action in ("rfi.requestResponse", "rfi.requestDistribution"):
                result["status"] = "pending"
            elif action in ("rfi.approveResponse", "rfi.approveDistribution"):
                result["status"] = "granted"
            elif action == "rfi.applyResponse":
                result.update(status="answered", rfiVersion=source["effect"]["result"]["version"], responseRevisionId=sealed["responseRevisionId"])
            else:
                record = source["effect"]["record"]
                result.update(status="distributed", rfiVersion=record["rfi_version"], distributionId=record["id"],
                              recipients=loads(record["recipients_json"]), syntheticMailSink=True, externalDelivery="not_attempted")
        return result

    def _verify_plan(self, action, resource_id, reviewed, source):
        plan, actor = reviewed["plan"], reviewed["login"]
        rid = source["rfiId"]
        if action == "rfi.create":
            record = source["record"]
            native = record["native"]
            drawings = [issued_drawing_proof(self.cipher, resource_id, item["revision"]["id"], current=True) for item in record["drawings"]]
            documents = [owned_revision_proof(self.cipher, resource_id, item["revision"]["id"], current=True) for item in record["documents"]]
            document_ids = {p["document"]["id"] for p in documents} | {p["evidence"]["document"]["id"] for p in drawings}
            rights = [document_rights_proof(self.cipher, resource_id, identifier, "project_use") for identifier in sorted(document_ids)]
            actual = {"person": record["person"], "source": {"projectId": resource_id, "sourceKind": SOURCE_KIND,
                "drawings": drawings, "documents": documents, "rights": rights},
                "nativeInput": {"subject": native["subject"], "question": native["question"],
                    "drawing_revision_ids": [p["revision"]["id"] for p in drawings],
                    "document_revision_ids": [p["revision"]["id"] for p in documents]}}
            if not self._same(actual, plan):
                raise RFIReceiptError("RFI creation changed the full reviewed issued source, rights or author")
            record = source["record"]
            if (not self._same(record["person"], plan["person"])
                    or not self._same(record["rightsAtCreation"], plan["source"]["rights"])
                    or record["sourceKind"] != SOURCE_KIND
                    or set(record) != {"id", "project_id", "rfi_id", "sourceKind", "created_by", "created_at", "person", "native", "creationEvent", "links", "drawings", "documents", "rightsAtCreation"}
                    or set(native) != {"id", "project_id", "sequence", "number", "subject", "question", "content_hash", "created_by", "created_at"}):
                raise RFIReceiptError("RFI creation changed its full original source, rights or canonical author")
        else:
            current = self.domain.source_proof(rid, current="currentRights" in plan["source"])
            # Only the declared lifecycle effects may differ. All original cited
            # evidence, issued drawing origins, current heads and source hashes
            # remain exactly the source packet checked under this lock.
            volatile = ("native", "responseRevisions", "distributionRevisions", "latestResponse", "latestDistribution", "answer", "distributions", "approvals")
            stable = {key: value for key, value in current.items() if key not in volatile}
            expected = {key: value for key, value in plan["source"].items() if key not in volatile}
            if not self._same(stable, expected):
                raise RFIReceiptError("RFI action changed its full reviewed source disclosure")
            if action in ("rfi.draftResponse", "rfi.setDistribution"):
                record, native = source["revision"]["record"], plan["nativeInput"]
                actual = {"response_text": record["response"], "cost_impact": record["costImpact"], "schedule_impact_days": record["scheduleImpactDays"]} if action == "rfi.draftResponse" else {"recipients": record["recipients"]}
                if (not self._same(actual, native) or not self._same(record["person"], plan["person"])
                        or record["native_version"] != plan["source"]["native"]["version"] + 1):
                    raise RFIReceiptError("RFI revision differs from its full exact reviewed native plan")
            else:
                proof = self.domain.approval_proof(source["approvalId"])
                approval, sealed = proof["record"], proof["source"]["record"]
                if (material_hash(reviewed["manifest"]) != approval["material_hash"]
                        or not self._same(reviewed["manifest"].get("governance"), approval["manifest"].get("governance"))):
                    raise RFIReceiptError("RFI authorization differs from its reviewed material and governance")
                if action in ("rfi.requestResponse", "rfi.requestDistribution"):
                    expected_context, digest = self.domain._review_context(plan["source"], self._operation(action))
                    if (approval["requested_by"] != actor or not self._same(sealed["person"], plan["person"])
                            or not self._same(sealed["context"], expected_context) or sealed["contextHash"] != digest):
                        raise RFIReceiptError("RFI request changed its exact reviewed context or current requester")
                    source["requestDeadline"] = {"checkedExpiresAt": reviewed["manifest"]["expires_at"],
                        "reviewStartedAt": reviewed["reviewClockStartedAt"], "completedAt": utcnow().isoformat()}
                    self._verify_request_deadline(approval, source["requestDeadline"])
                else:
                    if not self._same(self._request_original(source["approvalId"]), self._request_from_proof(plan["approval"])):
                        raise RFIReceiptError("RFI action substituted the reviewed original authorization")
                    column = "approver" if action in ("rfi.approveResponse", "rfi.approveDistribution") else "consumed_by"
                    if approval[column] != actor:
                        raise RFIReceiptError("RFI action changed its exact reviewed decision actor")

    @staticmethod
    def _request_from_proof(proof):
        row = proof["record"]
        return {"source": proof["source"], "request": proof["request"],
                "original": {key: row[key] for key in ("id", "operation", "subject_type", "subject_id", "actor_role", "policy_version",
                    "manifest", "manifest_hash", "material_hash", "nonce", "expires_at", "requested_by", "requested_at")}}

    def _verify_source(self, receipt):
        source, result, binding = (loads(receipt[key]) for key in ("source_json", "result_json", "binding_json"))
        if receipt["outcome"] == "refused":
            self._verify_refusal(receipt, source, result)
            return
        action, resource, typed, actor = receipt["fixed_action"], receipt["resource_id"], binding["canonicalTypedBody"], receipt["actor_login"]
        if source["kind"] != action.split(".")[1] or not self._same(self._source_original(source["rfiId"]), {key: source[key] for key in ("record", "sourceHash")}):
            raise RFIReceiptError("RFI receipt lost its original audited source")
        proof = self.domain.source_proof(source["rfiId"])
        self.domain.approval_inventory(project_ids=(proof["projectId"],))
        if action == "rfi.create":
            record = source["record"]
            drawings = [item["revision"]["id"] for item in record["drawings"]]
            documents = [item["revision"]["id"] for item in record["documents"]]
            if (resource != record["project_id"] or record["native"]["subject"] != typed["subject"].strip()
                    or record["native"]["question"] != typed["question"].strip() or not self._same(drawings, typed["drawingRevisionIds"])
                    or not self._same(documents, typed["documentRevisionIds"]) or record["created_by"] != actor
                    or record["person"]["personId"] != receipt["canonical_person_id"]):
                raise RFIReceiptError("RFI creation changed its typed question, ordered citations or canonical author")
        elif action in ("rfi.draftResponse", "rfi.setDistribution"):
            record = source["revision"]["record"]
            choices = proof["responseRevisions" if action == "rfi.draftResponse" else "distributionRevisions"]
            if (resource != source["rfiId"] or sum(self._same(item, source["revision"]) for item in choices) != 1
                    or record["created_by"] != actor or record["person"]["personId"] != receipt["canonical_person_id"]):
                raise RFIReceiptError("RFI revision lost its original source, event or canonical author")
            actual = {"responseText": record["response"], "costImpact": record["costImpact"], "scheduleImpactDays": record["scheduleImpactDays"]} if action == "rfi.draftResponse" else {"recipients": record["recipients"]}
            expected = {key: value.strip() if key == "responseText" else value for key, value in typed.items() if key != "fingerprint"}
            if not self._same(actual, expected):
                raise RFIReceiptError("RFI revision differs from its exact original typed values")
        else:
            approval = self.domain.approval_proof(source["approvalId"])
            row = approval["record"]
            request = self._request_original(source["approvalId"])
            if (row["operation"] != self._operation(action) or row["subject_id"] != source["rfiId"]
                    or resource != (source["rfiId"] if action in ("rfi.requestResponse", "rfi.requestDistribution") else source["approvalId"])
                    or not self._same(request, source["request"])):
                raise RFIReceiptError("RFI action changed its exact original operation, request or resource")
            if action in ("rfi.requestResponse", "rfi.requestDistribution"):
                if row["requested_by"] != actor or request["source"]["record"]["person"]["personId"] != receipt["canonical_person_id"]:
                    raise RFIReceiptError("RFI request changed its original canonical PM")
                self._verify_request_deadline(row, source["requestDeadline"], created_at=receipt["created_at"])
            elif action in ("rfi.approveResponse", "rfi.approveDistribution"):
                if row["approver"] != actor or not self._same(approval["grant"], source["grant"]):
                    raise RFIReceiptError("RFI original independent grant is unavailable")
            else:
                effect = self.domain.effect_proof(source["approvalId"])
                if not self._same(effect, source["effect"]) or row["consumed_by"] != actor or effect["applicator"]["personId"] != receipt["canonical_person_id"]:
                    raise RFIReceiptError("RFI original consumed authorization or outcome is unavailable")
                self._verify_command(source, actor)
        if not self._same(result, self._expected_result(action, source)):
            raise RFIReceiptError("RFI result differs from its literal exact original outcome")

    def _verify_request_deadline(self, approval, clock, *, created_at=None):
        if type(clock) is not dict or set(clock) != {"checkedExpiresAt", "reviewStartedAt", "completedAt"} or any(type(v) is not str for v in clock.values()):
            raise RFIReceiptError("RFI request lost its original checked policy clock")
        checked, actual, start, end, requested = (parse_iso(v) for v in (clock["checkedExpiresAt"], approval["expires_at"], clock["reviewStartedAt"], clock["completedAt"], approval["requested_at"]))
        if any(v.utcoffset() is None for v in (checked, actual, start, end, requested)):
            raise RFIReceiptError("RFI policy clocks require original timezone provenance")
        elapsed, shifted = (end-start).total_seconds(), (actual-checked).total_seconds()
        window = elapsed if checked.microsecond or actual.microsecond else int(end.timestamp())-int(start.timestamp())
        if (elapsed < 0 or shifted < 0 or shifted > window or checked < start
                or (requested-start).total_seconds() < -1 or (requested-end).total_seconds() > 1
                or created_at is not None and (parse_iso(created_at)-end).total_seconds() < -1):
            raise RFIReceiptError("RFI request changed its checked native policy deadline")

    def _event(self, action, entity, identifier):
        rows = self.cipher.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type=? AND entity_id=? ORDER BY seq", (action, entity, identifier))
        if len(rows) != 1:
            raise RFIReceiptError("RFI original exact audit event is unavailable")
        return rows[0]

    def _verify_command(self, source, actor):
        approval = source["request"]["original"]
        payload = {"approval_id": source["approvalId"], "operation": approval["operation"], "subject_id": source["rfiId"]}
        expected = source["effect"]["result"] if approval["operation"] == RESPONSE else self._distribution_result(source["effect"]["record"])
        row = self.cipher.db.one("SELECT * FROM idempotency WHERE op_id=?", (source["commandId"],))
        event = self._event("command.executed", "command", source["commandId"])
        if (source["commandId"] != "exec:" + source["approvalId"] or row is None or row["payload_hash"] != hash_json(payload)
                or row["result_json"] != canonical_json(expected) or event["actor"] != actor
                or not self._same(loads(event["payload_json"]), {"payload_hash": hash_json(payload)})):
            raise RFIReceiptError("RFI original command changed its exact payload, result or audited actor")
        created, audited = parse_iso(row["created_at"]), parse_iso(event["ts"])
        if (created.utcoffset() is None or audited.utcoffset() is None or not 0 <= (audited-created).total_seconds() <= 1
                or event["seq"] <= source["effect"]["event"]["seq"]):
            raise RFIReceiptError("RFI original command lost its original effect and audit chronology")

    def _snapshot(self):
        names = self.cipher.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return {"schema": self.cipher.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"),
                "tables": {row["name"]: self.cipher.db.query('SELECT * FROM "' + row["name"].replace('"', '""') + '"') for row in names}}

    def _verify_boundary(self, action, context, before, receipt, source, *, after=None):
        after = self._snapshot() if after is None else after
        if not self._same(before["schema"], after["schema"]) or before["tables"].keys() != after["tables"].keys():
            raise RFIReceiptError("RFI action changed workspace schema")
        added, changed, events = {}, {}, []
        if receipt is not None:
            added["rfi_action_receipts"] = {receipt["id"]}
            events.append((RECEIPT_ACTION, RECEIPT_ENTITY, receipt["id"]))
        aid, rid = source.get("approvalId"), source.get("rfiId")
        if source["kind"] == "refusal":
            changed["approvals"] = {aid: {"status", "invalidated_reason"}}
            events.append(("approval." + source["status"], "approval", aid))
        elif action == "rfi.create":
            record = source["record"]
            added.update(field_rfis={rid}, rfi_sources={record["id"]}, field_rfi_links={row["id"] for row in record["links"]},
                         drawing_references={item["reference"]["record"]["id"] for item in record["drawings"]})
            events += [("field.rfi_created", "field_rfi", rid), ("rfi.sources_recorded", "rfi_sources", record["id"])]
            events += [("drawing.referenced", "drawing_reference", item) for item in added["drawing_references"]]
        elif action in ("rfi.draftResponse", "rfi.setDistribution"):
            response = action == "rfi.draftResponse"
            record = source["revision"]["record"]
            table = "rfi_response_revisions" if response else "rfi_distribution_revisions"
            added[table] = {record["id"]}
            changed["field_rfis"] = {rid: {"version", "updated_at", *( ("draft_response", "draft_cost_impact", "draft_schedule_impact_days", "draft_response_hash") if response else ("distribution_recipients_json", "distribution_recipients_hash") )}}
            events += [("field.rfi_response_drafted" if response else "field.rfi_distribution_list_set", "field_rfi", rid),
                       ("rfi.response_revisions_recorded" if response else "rfi.distribution_revisions_recorded", table, record["id"])]
        elif action in ("rfi.requestResponse", "rfi.requestDistribution"):
            sealed = source["request"]["source"]["record"]
            added.update(approvals={aid}, rfi_approval_sources={sealed["id"]})
            events += [("approval.requested", "approval", aid), ("rfi.approval_sources_recorded", "rfi_approval_sources", sealed["id"])]
        elif action in ("rfi.approveResponse", "rfi.approveDistribution"):
            changed["approvals"] = {aid: {"status", "approver", "granted_at"}}
            events += [("approval.granted", "approval", aid), ("rfi.review_granted", "approval", aid)]
        else:
            added["idempotency"] = {source["commandId"]}
            changed["approvals"] = {aid: {"status", "consumed_by", "consumed_at"}}
            events += [("approval.consumed", "approval", aid), ("command.executed", "command", source["commandId"])]
            if action == "rfi.applyResponse":
                changed["field_rfis"] = {rid: {"status", "version", "response", "cost_impact", "schedule_impact_days", "response_hash", "approval_id", "updated_at", "answered_by", "answered_at"}}
                events.append(("field.rfi_answered", "field_rfi", rid))
            else:
                added["field_rfi_distributions"] = {source["effect"]["record"]["id"]}
                events.append(("field.rfi_distributed", "field_rfi", rid))
        if source["kind"] != "refusal" and action in ("rfi.draftResponse", "rfi.setDistribution", "rfi.applyResponse", "rfi.distribute"):
            invalidated = [row["id"] for row in before["tables"]["approvals"] if row["subject_type"] == "field_rfi" and row["subject_id"] == rid and row["status"] in ("pending", "granted") and row["id"] != aid]
            changed.setdefault("approvals", {}).update({identifier: {"status", "invalidated_reason"} for identifier in invalidated})
            events += [("approval.invalidated", "approval", identifier) for identifier in invalidated]
            for identifier in invalidated:
                row = self.cipher.approvals.get(identifier)
                if row["status"] != "invalidated":
                    raise RFIReceiptError("RFI revision omitted an originally disclosed open authorization invalidation")
        for table, old_rows in before["tables"].items():
            new_rows = after["tables"][table]
            if table == "audit_log":
                appended = new_rows[len(old_rows):]
                if (not self._same(old_rows, new_rows[:len(old_rows)])
                        or Counter((row["action"], row["entity_type"], row["entity_id"]) for row in appended) != Counter(events)
                        or any(row["actor"] != context["login"] for row in appended)):
                    raise RFIReceiptError("RFI action appended an unreviewed audit effect")
                continue
            if table not in added and table not in changed:
                if not self._same(old_rows, new_rows):
                    raise RFIReceiptError("RFI action changed an unrelated source or financial record")
                continue
            key = "op_id" if table == "idempotency" else "id"
            old, new = ({row[key]: row for row in rows} for rows in (old_rows, new_rows))
            if set(old)-set(new) or set(new)-set(old) != added.get(table, set()):
                raise RFIReceiptError("RFI action inserted or deleted an unreviewed resource")
            for identifier, old_row in old.items():
                columns = {column for column in old_row if not self._same(old_row[column], new[identifier][column])}
                if not columns <= changed.get(table, {}).get(identifier, set()):
                    raise RFIReceiptError("RFI action changed an unreviewed row or field")

    @staticmethod
    def _refusal_result(status):
        return {"code": "rfi_authorization_expired" if status == "expired" else "rfi_source_changed",
                "message": "The RFI authorization expired. Request fresh review." if status == "expired" else "The RFI source changed. Request fresh review.", "target": "approval"}

    def _terminal_proof(self, action, resource_id, context, before, exc):
        status = "expired" if isinstance(exc, ApprovalExpired) else "invalidated"
        after = self._snapshot()
        if self._same(before, after):
            result = self._refusal_result(status)
            raise APRefusal(423 if status == "expired" else 412, result["code"], result["message"], result["target"])
        if action not in ("rfi.approveResponse", "rfi.approveDistribution", "rfi.applyResponse", "rfi.distribute"):
            raise RFIReceiptError("This RFI action cannot commit authorization controls")
        old = next(row for row in before["tables"]["approvals"] if row["id"] == resource_id)
        proof = self.domain.approval_proof(resource_id)
        approval = proof["record"]
        if old["status"] != ("pending" if action in ("rfi.approveResponse", "rfi.approveDistribution") else "granted") or approval["status"] != status:
            raise RFIReceiptError("RFI refusal has no original legal terminal transition")
        if status == "expired":
            if approval["expires_at"] != approval["manifest"]["expires_at"] or parse_iso(approval["expires_at"]) > utcnow():
                raise RFIReceiptError("RFI refusal cannot invent or shorten its deadline")
        else:
            try:
                manifest = self.cipher._manifest(approval["operation"], approval["subject_id"], "pm")
                stale = material_hash(manifest) != approval["material_hash"] or not self._same(manifest.get("governance"), approval["manifest"].get("governance"))
            except ApprovalError:
                stale = True
            if not stale:
                raise RFIReceiptError("RFI stale refusal lacks independently changed source facts")
        row = self._event("approval." + status, "approval", resource_id)
        source = {"kind": "refusal", "approvalId": resource_id, "status": status, "request": self._request_original(resource_id), "event": {"seq": row["seq"], "hash": row["entry_hash"]}}
        self._verify_boundary(action, context, before, None, source, after=after)
        return source

    def _verify_refusal(self, receipt, source, result):
        if (receipt["fixed_action"] not in ("rfi.approveResponse", "rfi.approveDistribution", "rfi.applyResponse", "rfi.distribute")
                or source["kind"] != "refusal" or source["status"] not in ("expired", "invalidated")):
            raise RFIReceiptError("RFI refusal changed its fixed authorization action")
        self.domain.approval_proof(source["approvalId"])
        event = self._event("approval." + source["status"], "approval", source["approvalId"])
        if (receipt["resource_id"] != source["approvalId"] or not self._same(source["request"], self._request_original(source["approvalId"]))
                or not self._same(source["event"], {"seq": event["seq"], "hash": event["entry_hash"]}) or event["actor"] != receipt["actor_login"]
                or not self._same(result, self._refusal_result(source["status"])) or receipt["http_status"] != (423 if source["status"] == "expired" else 412)):
            raise RFIReceiptError("RFI refusal differs from its exact original terminal event")

    def integrity_checks(self):
        try:
            self.receipts.verify_integrity()
            for row in self.cipher.db.query("SELECT * FROM rfi_action_receipts"):
                self._verify_source(row)
            return {"ok": True, "reason": "RFI receipts retain their original audited effects"}
        except Exception:
            return {"ok": False, "reason": "RFI original action source proof is unavailable"}

    def close_checks(self, period_id):
        result = self.integrity_checks()
        return [] if result["ok"] else [{"kind": "rfi_action_receipt", **result}]

    def export(self):
        return {"integrity": self.integrity_checks(), "count": self.cipher.db.scalar("SELECT COUNT(*) FROM rfi_action_receipts")}
