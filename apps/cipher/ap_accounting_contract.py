"""scoped synthetic accounting reads; never seeds or delivers.

"""
from __future__ import annotations

import hashlib
import hmac

from .ap_contract import APRefusal, PROVENANCE, _not_found
from .ap_intake_contract import _locked
from .api_contract import MAX_SAFE_INTEGER
from .core.approvals import material_hash, material_part
from .core.ids import canonical_json, parse_iso, utcnow


OPERATION = "accounting.queue"
SUBJECT_TYPE = "accounting_plan"
ACTIONS = frozenset(("accounting.prepare", "accounting.request", "accounting.approve", "accounting.queue",
                     "accounting.deliver", "accounting.lookup", "accounting.reconcile"))
RESOURCE_TYPES = {"accounting.prepare": "bill", "accounting.request": "plan", "accounting.approve": "approval",
                  "accounting.queue": "approval", "accounting.deliver": "intent", "accounting.lookup": "intent",
                  "accounting.reconcile": "intent"}
COLLECTIONS = {"accounting-plans": "plan", "accounting-approvals": "approval", "accounting-intents": "intent"}
STATUSES = {"plan": ("prepared",), "approval": ("pending", "granted", "consumed", "expired", "invalidated"),
            "intent": ("queued", "submitting", "outcome_unknown", "simulated_accepted", "reconciled", "refused")}


def approval_proof(cipher, approval_id):
    return cipher.plugin("accounting").approval_proof(approval_id)


class APAccountingContract:
    def __init__(self, cipher, base, intake, exception, *, secret, worker=None):
        if (base.cipher is not cipher or intake.cipher is not cipher or exception.cipher is not cipher
                or type(secret) is not bytes or len(secret) < 32):
            raise ValueError("Accounting reads require the owned AP workspace and private server key.")
        self.cipher, self.base, self.intake, self.exception, self.secret = cipher, base, intake, exception, secret
        self.accounting = cipher.plugin("accounting")
        self.worker = worker

    def _sign(self, value):
        return hmac.new(self.secret, canonical_json(value).encode(), hashlib.sha256).hexdigest()

    def _scope(self, authority, identifier, kind):
        # Only project/bill references are inspected before access is established.
        sql = {
            "bill": "SELECT c.project_id,b.id AS bill_id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.id=?",
            "plan": "SELECT project_id,bill_id FROM accounting_plans WHERE id=?",
            "approval": "SELECT p.project_id,p.bill_id FROM approvals a JOIN accounting_plans p ON p.id=a.subject_id WHERE a.id=? AND a.operation='accounting.queue' AND a.subject_type='accounting_plan'",
            "intent": "SELECT p.project_id,p.bill_id FROM accounting_intents i JOIN accounting_plans p ON p.id=i.plan_id WHERE i.id=?",
        }.get(kind)
        if sql is None:
            raise APRefusal(422, "unsupported_resource", "Choose a supported accounting record.", "resource")
        row = self.cipher.db.one(sql, (identifier,))
        if row is None or row["project_id"] not in authority.project_ids:
            _not_found()
        self.intake._project(authority, row["project_id"])
        return row

    def _record(self, authority, identifier, kind):
        scope = self._scope(authority, identifier, kind)
        try:
            if kind == "bill":
                record = self.base._bill(authority, identifier)
            elif kind == "plan":
                record = self.accounting.plan(identifier)
            elif kind == "intent":
                record = self.accounting.intent(identifier)
            else:
                approval_proof(self.cipher, identifier)
                record = self.cipher.approvals.get(identifier)
                if record["actor_role"] != "accountant" or record["manifest"].get("actor_role") != "accountant":
                    raise APRefusal(422, "unsupported_authorization", "This accounting workflow requires its accountant authorization.", "approval")
            plan = (self.accounting.plan(record["subject_id"]) if kind == "approval" else
                    self.accounting.plan(record["plan_id"]) if kind == "intent" else record if kind == "plan" else None)
            if plan and (plan["project_id"] != scope["project_id"] or plan["bill_id"] != scope["bill_id"]):
                raise RuntimeError("accounting source scope changed")
            return record
        except APRefusal:
            raise
        except (RuntimeError, ValueError, TypeError, KeyError):
            raise APRefusal(423, "accounting_source_unavailable", "The accounting record's source history cannot be verified.", kind) from None

    @_locked
    def authorize(self, person_id, action, resource_id):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported synthetic accounting action.", "action")
        authority = self.base._authority(person_id)
        kind = RESOURCE_TYPES[action]
        scope = self._scope(authority, resource_id, kind)
        try:
            duty = self.accounting.require_accountant(authority.login, scope["project_id"])
        except (RuntimeError, ValueError, TypeError, KeyError):
            raise APRefusal(403, "actual_accountant_required", "This action requires the person's own current project accountant duty.", "duty") from None
        return {"personId": authority.person_id, "login": authority.login, "duty": "accountant",
                "projectId": scope["project_id"], "record": self._record(authority, resource_id, kind),
                "authority": authority, "accountantProof": duty}

    def current_mapping(self, authority, project_id):
        self.intake._project(authority, project_id)
        # This is server-selected seeded configuration; no browser selector.
        return self.accounting.current_mapping(project_id, actor=authority.login)

    def _version(self, authority, identifier, kind):
        scope = self._scope(authority, identifier, kind)
        record = self._record(authority, identifier, kind)
        plan = (self.accounting.plan(record["subject_id"]) if kind == "approval" else
                self.accounting.plan(record["plan_id"]) if kind == "intent" else record if kind == "plan" else None)
        try:
            current_mapping = self.current_mapping(authority, scope["project_id"])
        except (RuntimeError, ValueError, TypeError, KeyError):
            current_mapping = {"available": False}
        current = None
        if plan:
            try:
                manifest = self.cipher._manifest(OPERATION, plan["id"], "accountant")
                current = {"material": material_part(manifest), "governance": manifest.get("governance")}
            except (RuntimeError, ValueError, TypeError, KeyError):
                current = {"available": False}
        # The fixed public record's audited revision binds delivery history. A
        # private lease is bound only when present and is never exposed in DTOs.
        lease = self.accounting._proof("leases", record["last_lease_id"]) if kind == "intent" and record["last_lease_id"] else None
        private = {"provenance": PROVENANCE, "workspace": self.cipher.db.mode_status(), "authority": self.cipher.db.authority_status(),
                   "personId": authority.person_id, "scope": authority.scope_hash, "kind": kind, "record": record,
                   "billVersion": self.base._version(authority, scope["bill_id"]), "plan": plan,
                   "currentMapping": current_mapping, "currentManifest": current, "lease": lease}
        return "apac1-" + self._sign(private)

    @_locked
    def version(self, person_id, resource_id, resource_type):
        return self._version(self.base._authority(person_id), resource_id, resource_type)

    @staticmethod
    def _integer(value):
        if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
            raise APRefusal(423, "invalid_accounting_amount", "The accounting source's exact cents cannot be verified.", "amount")
        return value

    def _plan_value(self, authority, plan):
        payload = plan["payload"]
        bill = self.base._bill(authority, plan["bill_id"])
        bill_value = self.base._bill_value(authority, bill)
        lines = [{"sourceAccountCode": row["sourceAccountCode"], "account": row["account"],
                  "debitCents": self._integer(row["debitCents"]), "creditCents": self._integer(row["creditCents"]),
                  "projectRef": row["projectRef"], "vendorRef": row["vendorRef"], "memo": row["memo"]} for row in payload["lines"]]
        amounts = {line["sourceAccountCode"]: line for line in lines}
        names = {"5000": ("Installed work cost", "Synthetic installed work cost"),
                 "2000": ("Accounts payable", "Synthetic accounts payable"),
                 "2050": ("Retainage payable", "Synthetic retainage payable")}
        preview_lines = [{"id": f"{plan['id']}:{index}", "sourceAccountCode": line["sourceAccountCode"],
                          "sourceAccountName": names[line["sourceAccountCode"]][0],
                          "practiceAccountName": names[line["sourceAccountCode"]][1],
                          "debitCents": line["debitCents"], "creditCents": line["creditCents"],
                          "projectName": bill_value["projectName"], "supplierName": bill_value["supplierName"],
                          "memo": line["memo"]} for index, line in enumerate(lines, 1)]
        posting = self.cipher.bills.posting_receipt(plan["bill_id"])
        return {"id": plan["id"], "status": "prepared", "projectId": plan["project_id"], "billId": plan["bill_id"],
                "source": {"billId": bill["id"], "sequence": bill["sequence"], "projectId": bill["project_id"],
                           "projectName": bill_value["projectName"], "supplierId": bill["supplier_id"],
                           "supplierName": bill_value["supplierName"], "commitmentId": bill["commitment_id"],
                           "commitmentTitle": bill_value["commitmentTitle"], "currentBillStatus": bill["status"],
                           "postingReceiptId": payload["source"]["postingReceiptId"], "originalJournalId": plan["journal_id"]},
                "original": {"originalCostCents": amounts["5000"]["debitCents"],
                             "originalApCents": amounts.get("2000", {}).get("creditCents", 0),
                             "originalRetainageCents": amounts.get("2050", {}).get("creditCents", 0),
                             "sourcePeriod": self.base._period(payload["period"]["id"]),
                             "sourcePostedBy": self.base._person(posting["posted_by"]), "sourcePostedAt": posting["posted_at"]},
                "date": {"policy": payload["datePolicy"], "transactionDate": payload["transactionDate"],
                         "sourcePeriodId": payload["period"]["id"], "sourcePeriodEndDate": payload["period"]["endDate"],
                         "qualification": "synthetic_only"},
                "preview": {"lines": preview_lines, "debitTotalCents": self._integer(sum(line["debitCents"] for line in lines)),
                            "creditTotalCents": self._integer(sum(line["creditCents"] for line in lines))},
                "capability": {"source": "original_installed_work_posting_receipt", "route": payload["route"],
                               "simulation": True, "externalAccounting": "unavailable", "quickBooksAccepted": False,
                               "datePolicy": payload["datePolicy"], "liveDatePolicy": "unqualified",
                               "transactionKind": "aggregate_practice_journal", "dimensions": ["project", "supplier"],
                               "costTypeQualification": "unavailable", "taxQualification": "unavailable", "payment": "not_started"},
                "logicalOperationId": plan["logical_operation_id"], "payloadHash": plan["payload_hash"],
                "mapping": payload["mapping"], "route": payload["route"], "adapter": payload["adapter"],
                "datePolicy": payload["datePolicy"], "transactionDate": payload["transactionDate"], "period": payload["period"],
                "currency": "USD", "grossCostCents": amounts["5000"]["debitCents"],
                "netApCents": amounts.get("2000", {}).get("creditCents", 0),
                "retainageCents": amounts.get("2050", {}).get("creditCents", 0), "lines": lines,
                "preparedBy": self.base._person(plan["prepared_by"]), "preparedAt": plan["prepared_at"]}

    def _approval_value(self, approval):
        effective = approval["status"]
        if effective in ("pending", "granted"):
            if parse_iso(approval["expires_at"]) <= utcnow():
                effective = "expired"
            else:
                try:
                    current = self.cipher._manifest(OPERATION, approval["subject_id"], "accountant")
                    if material_hash(current) != approval["material_hash"] or current.get("governance") != approval["manifest"].get("governance"):
                        effective = "stale"
                except (RuntimeError, ValueError, TypeError, KeyError):
                    effective = "stale"
        return {"id": approval["id"], "planId": approval["subject_id"], "status": approval["status"], "effectiveStatus": effective,
                "requestedBy": self.base._person(approval["requested_by"]), "requestedAt": approval["requested_at"],
                "approvedBy": self.base._person(approval["approver"]), "approvedAt": approval["granted_at"],
                "expiresAt": approval["expires_at"]}

    def _intent_value(self, intent):
        return {"id": intent["id"], "planId": intent["plan_id"], "approvalId": intent["approval_id"], "status": intent["status"],
                "revision": intent["revision"], "logicalOperationId": intent["logical_operation_id"], "payloadHash": intent["payload_hash"],
                "queuedBy": self.base._person(intent["queued_by"]), "queuedAt": intent["queued_at"],
                "updatedBy": self.base._person(intent["updated_by"]), "updatedAt": intent["updated_at"],
                "lookupRequired": intent["lookup_required"], "hasAcceptance": intent["acceptance_id"] is not None,
                "simulation": True, "externalAccounting": "unavailable", "liveAccounting": "unavailable"}

    def _action_list(self, authority, candidates, identifier):
        from .ap_accounting_preflight import APAccountingPreflight
        preflight = APAccountingPreflight(self.cipher, self, secret=self.secret, worker=self.worker)
        actions, blocks = [], []
        for action in candidates:
            try:
                review = preflight.review(authority.person_id, action, identifier, {})
                if review["allowed"]:
                    actions.append(action)
                else:
                    block = next(check for check in review["checks"] if check["status"] == "blocked")
                    blocks.append({"action": action, "code": block["code"], "message": block["message"], "target": block["target"]})
            except APRefusal as exc:
                if exc.status != 403:
                    raise
                blocks.append({"action": action, "code": exc.code, "message": exc.message, "target": exc.target})
        return actions, blocks

    @_locked
    def preparation(self, person_id, bill_id):
        authority = self.base._authority(person_id)
        bill = self._record(authority, bill_id, "bill")
        try:
            mapping = self.current_mapping(authority, bill["project_id"])
            configuration = {"id": mapping["id"], "version": mapping["version"], "hash": mapping["mapping_hash"],
                             "route": mapping["route"], "adapter": mapping["adapter"], "datePolicy": mapping["datePolicy"]}
        except (RuntimeError, ValueError, TypeError, KeyError):
            configuration = None
        actions, blocks = self._action_list(authority, ["accounting.prepare"], bill_id)
        return {**PROVENANCE, "version": self._version(authority, bill_id, "bill"), "bill": self.base._bill_value(authority, bill),
                "mapping": configuration, "availableActions": actions, "blockedReasons": blocks,
                "simulation": True, "externalAccounting": "unavailable", "liveAccounting": "unavailable"}

    @_locked
    def plan_review(self, person_id, plan_id):
        authority = self.base._authority(person_id)
        plan = self._record(authority, plan_id, "plan")
        actions, blocks = self._action_list(authority, ["accounting.request"], plan_id)
        return {**PROVENANCE, "version": self._version(authority, plan_id, "plan"), "plan": self._plan_value(authority, plan),
                "availableActions": actions, "blockedReasons": blocks}

    @_locked
    def packet(self, person_id, approval_id):
        authority = self.base._authority(person_id)
        approval = self._record(authority, approval_id, "approval")
        plan = self.accounting.plan(approval["subject_id"])
        candidates = ["accounting.approve"] if approval["status"] == "pending" else ["accounting.queue"] if approval["status"] == "granted" else []
        actions, blocks = self._action_list(authority, candidates, approval_id)
        return {**PROVENANCE, "version": self._version(authority, approval_id, "approval"), "approval": self._approval_value(approval),
                "plan": self._plan_value(authority, plan), "availableActions": actions, "blockedReasons": blocks}

    @_locked
    def intent_review(self, person_id, intent_id):
        authority = self.base._authority(person_id)
        intent = self._record(authority, intent_id, "intent")
        plan = self.accounting.plan(intent["plan_id"])
        actions, blocks = self._action_list(authority, ["accounting.deliver", "accounting.lookup", "accounting.reconcile"], intent_id)
        return {**PROVENANCE, "version": self._version(authority, intent_id, "intent"), "intent": self._intent_value(intent),
                "plan": self._plan_value(authority, plan), "availableActions": actions, "blockedReasons": blocks,
                "deliveryAdmission": "disposable-memory-practice-only"}

    @_locked
    def read(self, person_id, collection, *, project_id=None, status=None, search="", top=50, cursor=None):
        kind = COLLECTIONS.get(collection)
        if kind is None or type(top) is not int or not 1 <= top <= 100 or status is not None and status not in STATUSES[kind]:
            raise APRefusal(422, "invalid_query", "Choose a supported collection, status and page size.", "query")
        if type(search) is not str or len(search) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in search):
            raise APRefusal(422, "invalid_query", "Use bounded search text.", "search")
        authority = self.base._authority(person_id)
        if project_id is not None:
            self.intake._project(authority, project_id)
        pairs = []
        for project in ((project_id,) if project_id else authority.project_ids):
            self.intake._project(authority, project)
            # Scoped audited inventories detect deleted records without exposing
            # unrelated record IDs or calculating cross-project aggregates.
            inventory = self.accounting.plan_inventory if kind == "plan" else self.accounting.intent_inventory if kind == "intent" else self.accounting.approval_inventory
            rows = inventory(project_ids=(project,))
            for row in rows:
                record = self._record(authority, row["id"], kind)
                value = self._plan_value(authority, record) if kind == "plan" else self._intent_value(record) if kind == "intent" else self._approval_value(record)
                value["version"] = self._version(authority, row["id"], kind)
                if status is not None and value["status"] != status:
                    continue
                if search and not any(search.casefold() in str(value.get(key, "")).casefold() for key in ("id", "billId", "planId", "logicalOperationId")):
                    continue
                pairs.append(((str(value.get("preparedAt", value.get("queuedAt", value.get("requestedAt", "")))), value["id"]), value))
        pairs.sort(key=lambda pair: pair[0])
        binding = self._sign({"person": authority.person_id, "scope": authority.scope_hash, "collection": collection,
                              "project": project_id, "status": status, "search": search, "top": top})
        last = self.base._cursor_key(cursor, binding)
        selected = [pair for pair in pairs if last is None or pair[0] > last]
        page = selected[:top]
        return {**PROVENANCE, "collection": collection, "projectId": project_id, "value": [pair[1] for pair in page], "count": len(pairs),
                "nextCursor": self.base._token({"v": 1, "binding": binding, "last": list(page[-1][0])}) if len(selected) > top else None,
                "facets": {"statuses": [{"value": item, "count": sum(pair[1]["status"] == item for pair in pairs)}
                                        for item in sorted({pair[1]["status"] for pair in pairs})]}, "totals": {}}
