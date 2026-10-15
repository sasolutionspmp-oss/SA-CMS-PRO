"""Six fixed local library effects with original proofs and atomic receipts."""
from collections import Counter
from contextlib import contextmanager
from uuid import UUID

from .ap_contract import APRefusal
from .core.api_receipts import APIRepeatabilityConflict
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash
from .core.ids import canonical_json, hash_json, loads, new_id, parse_iso, utcnow
from .domain.library import EFFECT_KIND, OPERATION, SOURCE_KIND
from .library_receipts import (LibraryReceipts, LibraryReceiptError, RECEIPT_ACTION, RECEIPT_ENTITY,
                               require_other_namespaces)
from .library_wire import ACTIONS, CONTRACT_VERSION

LABELS = {"effectKind": EFFECT_KIND, "journalCountDelta": 0, "apBalanceDeltaCents": 0,
          "arBalanceDeltaCents": 0, "providerCallsDelta": 0}


class LibraryActionRunner:
    def __init__(self, cipher, contract, preflight):
        if contract.cipher is not cipher or preflight.cipher is not cipher or preflight.contract is not contract:
            raise ValueError("Library actions require one owned scoped runtime")
        self.cipher, self.contract, self.preflight = cipher, contract, preflight
        self.domain = cipher.plugin("library")
        self.receipts = LibraryReceipts(cipher.db, cipher.audit)

    @staticmethod
    def _same(left, right):
        return canonical_json(left) == canonical_json(right)

    @contextmanager
    def _transaction(self):
        with self.cipher.db.transaction() as conn:
            name = new_id("library_api")
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
            raise APRefusal(422, "invalid_action", "Choose a supported library action.", "action")
        try:
            normalized = str(UUID(key)) if type(key) is str and len(key) == 36 else None
        except (ValueError, AttributeError):
            normalized = None
        if normalized is None or normalized != key.casefold():
            raise APRefusal(422, "invalid_repeatability_key", "Repeatability-Request-ID must be a UUID.", "Repeatability-Request-ID")
        if type(if_match) is not str or not if_match or len(if_match) > 256:
            raise APRefusal(422, "missing_record_version", "Supply the library version reviewed for this action.", "If-Match")
        typed = self.preflight._body(action, body, effect=True)
        fingerprint = body.get("fingerprint")
        if type(fingerprint) is not str or not fingerprint or not fingerprint.isascii() or len(fingerprint) > 256:
            raise APRefusal(422, "invalid_fingerprint", "Supply the original library review fingerprint.", "fingerprint")
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
                    raise PermissionError("Library practice effects require disposable memory")
                context = self.contract.authorize(person_id, action, resource_id)
                require_other_namespaces(self.cipher.db, self.cipher.audit, context["personId"], key, action, binding)
                receipt = self.receipts.find(context["personId"], key)
                if receipt is not None:
                    if receipt["binding_json"] != canonical_json(binding):
                        raise APIRepeatabilityConflict("This key belongs to a different original library request")
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
                        raise LibraryReceiptError("Library authority changed within the locked review")
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
            raise APRefusal(403, "action_not_authorized", "Your current project duties do not permit this library action.") from None
        except ApprovalError:
            raise APRefusal(409, "action_refused", "This library action cannot proceed. Refresh its review.") from None
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
        stored = self.cipher.db.one("SELECT * FROM library_action_receipts WHERE id=?", (returned["id"],))
        fields = {"workspace_id": workspace, "canonical_person_id": expected["person_id"], "actor_login": expected["actor_login"],
                  "repeatability_uuid": expected["repeatability_uuid"], "contract_version": CONTRACT_VERSION,
                  "fixed_action": expected["action"], "resource_id": expected["resource_id"],
                  "binding_json": canonical_json(expected["binding"]), "result_json": canonical_json(expected["result"]),
                  "source_json": canonical_json(expected["source"]), "outcome": expected["outcome"], "http_status": expected["http_status"]}
        if (stored is None or not self._same(stored, returned) or not self._same(arguments, expected)
                or any(not self._same(stored[field], value) for field, value in fields.items())):
            raise LibraryReceiptError("Library receipt changed its exact original reviewed invocation")
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

    def _revision_original(self, entry_id, revision_id):
        proof = self.domain.entry_proof(entry_id)
        revisions = [r for r in proof["revisions"] if r["record"]["id"] == revision_id]
        heads = [h for h in proof["heads"] if h["record"]["revision_id"] == revision_id]
        if len(revisions) != 1 or len(heads) != 1:
            raise LibraryReceiptError("Library original revision or current-pointer birth is missing")
        return {"entry": proof["entry"], "revision": revisions[0], "head": heads[0]}

    def _plan_original(self, plan_id):
        proof = self.domain.plan_proof(plan_id)
        record = proof["plan"]["record"]
        source = self._revision_original(record["entry_id"], record["revision_id"])
        if record["sourceHeadId"] != source["head"]["record"]["id"]:
            raise LibraryReceiptError("Reference plan lost its original authored source pointer")
        return {"plan": proof["plan"], **source}

    def _request_original(self, approval_id):
        proof = self.domain.approval_proof(approval_id)
        approval = proof["approval"]
        return {"requestEvent": proof["requestEvent"], "manifestHash": approval["manifest_hash"], "materialHash": approval["material_hash"],
                "requestedBy": approval["requested_by"], "requestedAt": approval["requested_at"], "expiresAt": approval["expires_at"]}

    def _apply(self, action, resource_id, context):
        actor = context["login"]
        if action in ("library.create", "library.revise"):
            effect = self.domain.create(resource_id, context["typed"], actor=actor) if action == "library.create" else self.domain.revise(resource_id, context["typed"], actor=actor)
            source = {"kind": "revision", **self._revision_original(effect["entry"]["record"]["id"], effect["currentRevisionId"])}
        elif action == "library.prepareReference":
            effect = self.domain.prepare_reference(resource_id, context["typed"], actor=actor)
            source = {"kind": "plan", **self._plan_original(effect["id"])}
        elif action == "library.requestAdoption":
            effect = self.cipher.request_approval(OPERATION, resource_id, actor_role="pm", requested_by=actor)
            source = {"kind": "request", "approvalId": effect["id"], "request": self._request_original(effect["id"]), **self._plan_original(resource_id)}
        elif action == "library.approveAdoption":
            self.cipher.approve(resource_id, approver=actor, approver_role="pm")
            proof = self.domain.approval_proof(resource_id)
            source = {"kind": "grant", "approvalId": resource_id, "request": self._request_original(resource_id), "grantEvent": proof["grantEvent"],
                      **self._plan_original(proof["approval"]["subject_id"])}
        else:
            effect = self.cipher.execute(resource_id, actor=actor)
            original = self.domain.original_reference_proof(effect.result["referenceId"])
            source = {"kind": "adoption", "approvalId": resource_id, "original": original, "commandId": "exec:" + resource_id,
                      **self._plan_original(original["record"]["plan_id"])}
        return self._expected_result(action, source), source

    def _expected_result(self, action, source):
        entry, revision = source["entry"]["record"], source["revision"]["record"]
        result = {"action": action, "entryId": entry["id"], "revisionId": revision["id"], **LABELS}
        if action in ("library.create", "library.revise"):
            result.update(status="draft", revision=revision["revision"], contentHash=revision["contentHash"])
        else:
            plan = source["plan"]["record"]
            result.update(planId=plan["id"], status="prepared" if action == "library.prepareReference" else
                          "pending" if action == "library.requestAdoption" else "granted" if action == "library.approveAdoption" else "adopted_reference")
            if "approvalId" in source:
                result["approvalId"] = source["approvalId"]
            if action == "library.applyAdoption":
                result.update(referenceId=source["original"]["record"]["id"], contentHash=revision["contentHash"],
                              targetLocator=plan["targetLocator"], purpose=plan["purpose"])
        return result

    def _verify_plan(self, action, resource_id, reviewed, source):
        plan, actor = reviewed["plan"], reviewed["login"]
        revision, entry = source["revision"]["record"], source["entry"]["record"]
        if action in ("library.create", "library.revise"):
            actual = {"person": revision["actor"], "projectId": revision["project_id"],
                      **{k: revision[k] for k in ("text", "contentHash", "byteCount", "encoding", "sourceLocator")}}
            if action == "library.create":
                actual.update(kind=entry["kind"], title=entry["title"], sourceKind=SOURCE_KIND)
            else:
                original = plan["original"]
                if (revision["previousRevisionId"] != original["currentRevisionId"] or revision["revision"] != original["currentRevision"]["record"]["revision"] + 1
                        or source["head"]["record"]["previousHeadId"] != original["currentHead"]["record"]["id"]):
                    raise LibraryReceiptError("Authored revision differs from its reviewed immediate predecessor")
                actual.update(original=original, changeReason=revision["changeReason"])
            if not self._same(actual, plan):
                raise LibraryReceiptError("Authored text differs from the full reviewed native plan")
        elif action == "library.prepareReference":
            record = source["plan"]["record"]
            actual = {"person": record["actor"], "source": self.domain.revision_proof(resource_id, current=True),
                      "targetLocator": record["targetLocator"], "purpose": record["purpose"], "effectKind": record["effectKind"]}
            if not self._same(actual, plan):
                raise LibraryReceiptError("Reference plan differs from its exact reviewed source and target")
        else:
            proof = self.domain.approval_proof(source["approvalId"])
            approval = proof["approval"]
            if (material_hash(reviewed["manifest"]) != approval["material_hash"]
                    or not self._same(reviewed["manifest"].get("governance"), approval["manifest"].get("governance"))):
                raise LibraryReceiptError("Reference authorization differs from its reviewed material or governance")
            # Only the reviewed authorization lifecycle changes. Every other
            # original source row and current right/role fact remains unchanged
            # under the separate exact row boundary below.
            if action == "library.requestAdoption" and approval["requested_by"] != actor:
                raise LibraryReceiptError("Reference request changed its actual preparing PM")
            if action == "library.requestAdoption":
                # Native request construction generates a fresh nonce/deadline.
                # Its deadline may cross a real second during local work, but
                # may not acquire an unreviewed lifetime or shorten the policy.
                source["requestDeadline"] = {"checkedExpiresAt": reviewed["manifest"]["expires_at"],
                    "reviewStartedAt": reviewed["reviewClockStartedAt"], "completedAt": utcnow().isoformat()}
                self._verify_request_deadline(approval, source["requestDeadline"])
            if action == "library.approveAdoption" and approval["approver"] != actor:
                raise LibraryReceiptError("Reference grant changed its actual reviewing PM")
            if action == "library.applyAdoption" and approval["consumed_by"] != actor:
                raise LibraryReceiptError("Reference adoption changed its actual applying PM")

    def _verify_source(self, receipt):
        source, result, binding = (loads(receipt[k]) for k in ("source_json", "result_json", "binding_json"))
        if receipt["outcome"] == "refused":
            self._verify_refusal(receipt, source, result)
            return
        action, resource_id, typed = receipt["fixed_action"], receipt["resource_id"], binding["canonicalTypedBody"]
        expected_kind = {"library.create": "revision", "library.revise": "revision", "library.prepareReference": "plan",
                         "library.requestAdoption": "request", "library.approveAdoption": "grant", "library.applyAdoption": "adoption"}[action]
        if source["kind"] != expected_kind:
            raise LibraryReceiptError("Library original action changed its fixed source kind")
        original = self._revision_original(source["entry"]["record"]["id"], source["revision"]["record"]["id"])
        if not self._same(original, {k: source[k] for k in original}):
            raise LibraryReceiptError("Library original revision differs from its exact audited source")
        entry, revision = original["entry"]["record"], original["revision"]["record"]
        self.domain.approval_inventory(project_ids=(entry["project_id"],))
        if action == "library.create":
            if (resource_id != entry["project_id"] or revision["revision"] != 1 or revision["previousRevisionId"] is not None
                    or entry["kind"] != typed["kind"] or entry["title"] != typed["title"].strip()):
                raise LibraryReceiptError("Library creation lost its original typed project or entry")
        elif action == "library.revise":
            if (resource_id != entry["id"] or revision["previousRevisionId"] != typed["previousRevisionId"]
                    or revision["changeReason"] != typed["changeReason"].strip()):
                raise LibraryReceiptError("Library revision lost its typed predecessor or reason")
        if action in ("library.create", "library.revise"):
            if (revision["text"] != typed["text"] or revision["sourceLocator"] != typed["sourceLocator"].strip()
                    or revision["actor"]["login"] != receipt["actor_login"] or revision["actor"]["personId"] != receipt["canonical_person_id"]):
                raise LibraryReceiptError("Library revision changed its original exact authored bytes or person")
        else:
            plan = source["plan"]["record"]
            if not self._same(self._plan_original(plan["id"]), {k: source[k] for k in ("plan", "entry", "revision", "head")}):
                raise LibraryReceiptError("Reference plan lost its original authored source")
            if action == "library.prepareReference":
                if (resource_id != revision["id"] or plan["targetLocator"] != typed["targetLocator"].strip()
                        or plan["purpose"] != typed["purpose"].strip() or plan["actor"]["personId"] != receipt["canonical_person_id"]
                        or plan["actor"]["login"] != receipt["actor_login"]):
                    raise LibraryReceiptError("Reference plan changed its original target, purpose or PM")
            else:
                proof = self.domain.approval_proof(source["approvalId"])
                approval = proof["approval"]
                if approval["subject_id"] != plan["id"] or resource_id != (plan["id"] if action == "library.requestAdoption" else source["approvalId"]):
                    raise LibraryReceiptError("Reference authorization changed its fixed original resource")
                if action in ("library.requestAdoption", "library.approveAdoption"):
                    if not self._same(self._request_original(source["approvalId"]), source["request"]):
                        raise LibraryReceiptError("Reference request lost its original immutable approval")
                    if action == "library.requestAdoption" and approval["requested_by"] != receipt["actor_login"]:
                        raise LibraryReceiptError("Reference request lost its original PM")
                    if action == "library.requestAdoption":
                        self._verify_request_deadline(approval, source["requestDeadline"], created_at=receipt["created_at"])
                    if action == "library.approveAdoption":
                        if (approval["approver"] != receipt["actor_login"] or not self._same(proof["grantEvent"], source["grantEvent"])):
                            raise LibraryReceiptError("Reference grant lost its original independent PM event")
                else:
                    if not self._same(self.domain.original_reference_proof(source["original"]["record"]["id"]), source["original"]):
                        raise LibraryReceiptError("Adopted reference changed its original reviewed text copy")
                    self._verify_command(source, receipt)
        if not self._same(result, self._expected_result(action, source)):
            raise LibraryReceiptError("Library result differs from its literal original source outcome")

    def _verify_request_deadline(self, approval, clock, *, created_at=None):
        if type(clock) is not dict or set(clock) != {"checkedExpiresAt", "reviewStartedAt", "completedAt"} or any(type(v) is not str for v in clock.values()):
            raise LibraryReceiptError("Reference request lost its original checked policy clock")
        checked, actual, start, end, requested = (parse_iso(v) for v in
            (clock["checkedExpiresAt"], approval["expires_at"], clock["reviewStartedAt"], clock["completedAt"], approval["requested_at"]))
        if any(v.utcoffset() is None for v in (checked, actual, start, end, requested)):
            raise LibraryReceiptError("Reference policy clocks require original timezone provenance")
        elapsed, shifted = (end-start).total_seconds(), (actual-checked).total_seconds()
        observed_seconds = int(end.timestamp()) - int(start.timestamp())
        if (elapsed < 0 or shifted < 0 or shifted > observed_seconds or checked.microsecond or actual.microsecond
                or checked < start or (requested-start).total_seconds() < -1 or (requested-end).total_seconds() > 1
                or created_at is not None and (parse_iso(created_at)-end).total_seconds() < -1):
            raise LibraryReceiptError("Reference request changed its checked native policy deadline")

    def _verify_command(self, source, receipt):
        original = source["original"]["record"]
        payload = {"approval_id": source["approvalId"], "operation": OPERATION, "subject_id": original["plan_id"], "person_id": receipt["canonical_person_id"]}
        cached = self.cipher.db.one("SELECT * FROM idempotency WHERE op_id=?", (source["commandId"],))
        self.domain._command_proof(source["commandId"], payload, cached)
        if original["actor"]["login"] != receipt["actor_login"] or source["commandId"] != "exec:" + source["approvalId"]:
            raise LibraryReceiptError("Reference command changed its original actual applying PM")

    def _snapshot(self):
        names = self.cipher.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return {"schema": self.cipher.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"),
                "tables": {r["name"]: self.cipher.db.query('SELECT * FROM "' + r["name"].replace('"', '""') + '"') for r in names}}

    def _verify_boundary(self, action, context, before, receipt, source, *, after=None):
        after = self._snapshot() if after is None else after
        if not self._same(before["schema"], after["schema"]) or before["tables"].keys() != after["tables"].keys():
            raise LibraryReceiptError("Library action changed workspace schema")
        added, changed, events = {}, {}, []
        if receipt is not None:
            added["library_action_receipts"] = {receipt["id"]}
            events.append((RECEIPT_ACTION, RECEIPT_ENTITY, receipt["id"]))
        if source["kind"] == "refusal":
            changed["approvals"] = {source["approvalId"]: {"status", "invalidated_reason"}}
            events.append(("approval." + source["status"], "approval", source["approvalId"]))
        elif action in ("library.create", "library.revise"):
            entry, revision, head = (source[k]["record"] for k in ("entry", "revision", "head"))
            added.update(library_revisions={revision["id"]}, library_heads={head["id"]}, document_revisions={revision["evidence_revision_id"]})
            events += [("library.revisions_recorded", "library_revisions", revision["id"]), ("library.heads_recorded", "library_heads", head["id"]),
                       ("document.revised", "document", entry["document_id"])]
            if action == "library.create":
                added.update(library_entries={entry["id"]}, documents={entry["document_id"]})
                events += [("library.entries_recorded", "library_entries", entry["id"]), ("document.registered", "document", entry["document_id"])]
        elif action == "library.prepareReference":
            plan_id = source["plan"]["record"]["id"]
            added["library_plans"] = {plan_id}
            events.append(("library.plans_recorded", "library_plans", plan_id))
        elif action == "library.requestAdoption":
            added["approvals"] = {source["approvalId"]}
            events.append(("approval.requested", "approval", source["approvalId"]))
        elif action == "library.approveAdoption":
            changed["approvals"] = {source["approvalId"]: {"status", "approver", "granted_at"}}
            events.append(("approval.granted", "approval", source["approvalId"]))
        else:
            original = source["original"]["record"]
            added.update(library_adoptions={original["id"]}, idempotency={source["commandId"]})
            changed["approvals"] = {source["approvalId"]: {"status", "consumed_by", "consumed_at"}}
            events += [("approval.consumed", "approval", source["approvalId"]), ("library.adoptions_recorded", "library_adoptions", original["id"]),
                       ("command.executed", "command", source["commandId"])]
        for table, old_rows in before["tables"].items():
            new_rows = after["tables"][table]
            if table == "audit_log":
                if (not self._same(old_rows, new_rows[:len(old_rows)])
                        or Counter((r["action"], r["entity_type"], r["entity_id"]) for r in new_rows[len(old_rows):]) != Counter(events)
                        or any(r["actor"] != context["login"] for r in new_rows[len(old_rows):])):
                    raise LibraryReceiptError("Library action appended an unreviewed audit effect")
                continue
            if table not in added and table not in changed:
                if not self._same(old_rows, new_rows):
                    raise LibraryReceiptError("Library action changed an unrelated source or financial record")
                continue
            key = "op_id" if table == "idempotency" else "id"
            old, new = ({r[key]: r for r in rows} for rows in (old_rows, new_rows))
            if set(old)-set(new) or set(new)-set(old) != added.get(table, set()):
                raise LibraryReceiptError("Library action inserted or deleted an unreviewed resource")
            for identifier, old_row in old.items():
                columns = {column for column in old_row if not self._same(old_row[column], new[identifier][column])}
                if not columns <= changed.get(table, {}).get(identifier, set()):
                    raise LibraryReceiptError("Library action changed an unreviewed row or field")

    @staticmethod
    def _refusal_result(status):
        return {"code": "library_authorization_expired" if status == "expired" else "library_source_changed",
                "message": "The library authorization expired. Request fresh review." if status == "expired" else
                           "The library source changed. Request fresh review.", "target": "approval"}

    def _terminal_proof(self, action, resource_id, context, before, exc):
        status = "expired" if isinstance(exc, ApprovalExpired) else "invalidated"
        after = self._snapshot()
        if self._same(before, after):
            result = self._refusal_result(status)
            raise APRefusal(423 if status == "expired" else 412, result["code"], result["message"], result["target"])
        if action not in ("library.approveAdoption", "library.applyAdoption"):
            raise LibraryReceiptError("This library action cannot commit authorization controls")
        old = next(row for row in before["tables"]["approvals"] if row["id"] == resource_id)
        proof = self.domain.approval_proof(resource_id)
        approval = proof["approval"]
        if old["status"] != ("pending" if action == "library.approveAdoption" else "granted") or approval["status"] != status:
            raise LibraryReceiptError("Library refusal has no original legal terminal transition")
        if status == "expired":
            if approval["expires_at"] != approval["manifest"]["expires_at"] or parse_iso(approval["expires_at"]) > utcnow():
                raise LibraryReceiptError("Library refusal cannot invent or shorten its original deadline")
        else:
            genuinely_stale = False
            try:
                current = self.cipher._manifest(OPERATION, approval["subject_id"], "pm")
                genuinely_stale = (material_hash(current) != approval["material_hash"]
                                   or not self._same(current.get("governance"), approval["manifest"].get("governance")))
            except ApprovalError:
                genuinely_stale = True
            if not genuinely_stale:
                raise LibraryReceiptError("Library stale refusal lacks independently changed source facts")
        rows = self.cipher.db.query("SELECT * FROM audit_log WHERE action=? AND entity_type='approval' AND entity_id=? ORDER BY seq", ("approval."+status, resource_id))
        source = {"kind": "refusal", "approvalId": resource_id, "status": status, "request": self._request_original(resource_id),
                  "event": {"seq": rows[-1]["seq"], "hash": rows[-1]["entry_hash"]}}
        self._verify_boundary(action, context, before, None, source, after=after)
        return source

    def _verify_refusal(self, receipt, source, result):
        if receipt["fixed_action"] not in ("library.approveAdoption", "library.applyAdoption") or source["kind"] != "refusal" or source["status"] not in ("expired", "invalidated"):
            raise LibraryReceiptError("Library refusal changed its fixed authorization action")
        proof = self.domain.approval_proof(source["approvalId"])
        event = self.cipher.db.one("SELECT * FROM audit_log WHERE seq=?", (source["event"]["seq"],))
        if (receipt["resource_id"] != source["approvalId"] or event is None or event["entry_hash"] != source["event"]["hash"]
                or event["action"] != "approval."+source["status"] or event["entity_type"] != "approval" or event["entity_id"] != source["approvalId"]
                or event["actor"] != receipt["actor_login"] or not self._same(source["request"], self._request_original(source["approvalId"]))
                or not self._same(result, self._refusal_result(source["status"])) or receipt["http_status"] != (423 if source["status"] == "expired" else 412)):
            raise LibraryReceiptError("Library refusal differs from its exact original terminal event")
        self.domain.approval_inventory(project_ids=(proof["plan"]["plan"]["record"]["project_id"],))

    def integrity_checks(self):
        try:
            self.receipts.verify_integrity()
            for row in self.cipher.db.query("SELECT * FROM library_action_receipts"):
                self._verify_source(row)
            return {"ok": True, "reason": "Library receipts retain their original audited effects"}
        except Exception:
            return {"ok": False, "reason": "Library original action source proof is unavailable"}

    def close_checks(self, period_id):
        result = self.integrity_checks()
        return [] if result["ok"] else [{"kind": "library_action_receipt", **result}]

    def export(self):
        return {"integrity": self.integrity_checks(), "count": self.cipher.db.scalar("SELECT COUNT(*) FROM library_action_receipts")}
