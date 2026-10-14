"""Scoped source-backed exception and correction reads for the AP practice entry."""
from __future__ import annotations

import hashlib
import hmac

from .ap_contract import APRefusal, PROVENANCE, _invalid_record, _money, _not_found
from .ap_intake_contract import _locked
from .core.approvals import material_hash, material_part
from .core.ids import canonical_json, loads, parse_iso, utcnow


CORRECTION_OPERATION = "bill.correct"
ACTIONS = frozenset(("invoice.revise", "invoice.reject", "invoice.reviewDuplicate", "bill.cancel",
                     "bill.prepareCorrection", "bill.requestCorrection", "bill.approveCorrection", "bill.executeCorrection"))
RESOURCE_TYPES = {action: "invoice" if action.startswith("invoice.") else "approval" if action in
                  ("bill.approveCorrection", "bill.executeCorrection") else "bill" for action in ACTIONS}
APPROVAL_STATUSES = ("pending", "granted", "consumed", "expired", "invalidated")


class APExceptionContract:
    def __init__(self, cipher, base, intake, *, secret):
        if base.cipher is not cipher or intake.cipher is not cipher or type(secret) is not bytes or len(secret) < 32:
            raise ValueError("Exception reads require the same owned AP workspace and private server key.")
        self.cipher, self.base, self.intake, self.secret = cipher, base, intake, secret
        self.ap = cipher.plugin("ap_intake")

    def _sign(self, value):
        return hmac.new(self.secret, canonical_json(value).encode(), hashlib.sha256).hexdigest()

    def _supported_bill(self, authority, bill_id):
        try:
            bill = self.base._bill(authority, bill_id)
        except APRefusal as exc:
            if exc.code == "invalid_record":
                raise APRefusal(423, "exception_source_unavailable", "The bill's exception source history cannot be verified.", "bill") from None
            raise
        if (bill["transfers"] or any(_money(bill[key]) for key in
                ("cumulative_stored", "stored_added_this_period", "stored_transferred_this_period"))):
            raise APRefusal(422, "unsupported_stored_material", "This exception workflow currently supports installed-work bills.", "bill")
        if self.cipher.db.one("SELECT id FROM procurement_awards WHERE commitment_id=?", (bill["commitment_id"],)):
            raise APRefusal(422, "unsupported_purchase_order", "This exception workflow currently supports progress subcontracts.", "bill")
        return bill

    def _invoice(self, authority, invoice_id):
        inv = self.intake._invoice(authority, invoice_id)
        if inv["commitment_id"] is None:
            raise APRefusal(422, "unsupported_invoice", "This exception workflow requires a progress subcontract invoice.", "invoice")
        if self.cipher.db.one("SELECT id FROM procurement_awards WHERE commitment_id=?", (inv["commitment_id"],)):
            raise APRefusal(422, "unsupported_purchase_order", "This exception workflow currently supports progress subcontracts.", "invoice")
        for row in self.cipher.db.query("SELECT id FROM bills WHERE supplier_invoice_id=? ORDER BY sequence,id", (invoice_id,)):
            self._supported_bill(authority, row["id"])
        return inv

    def _approval(self, authority, approval_id):
        row = self.cipher.db.one("SELECT a.id,b.id AS bill_id,c.project_id FROM approvals a JOIN bills b ON a.subject_id=b.id AND a.subject_type='bill' JOIN commitments c ON c.id=b.commitment_id WHERE a.id=? AND a.operation=?", (approval_id, CORRECTION_OPERATION))
        if row is None or row["project_id"] not in authority.project_ids:
            _not_found()
        self._supported_bill(authority, row["bill_id"])
        self.cipher.bills.correction_approval_proof(approval_id)
        approval = self.cipher.approvals.get(approval_id)
        if approval["actor_role"] != "accountant" or approval["manifest"].get("actor_role") != "accountant":
            raise APRefusal(422, "unsupported_authorization", "This practice correction requires the accountant workflow.", "approval")
        return approval

    def _correction(self, bill_id):
        try:
            values = self.cipher.bills.correction_inventory(bill_id)
        except RuntimeError:
            raise APRefusal(423, "correction_source_unavailable", "The bill's correction source history cannot be verified.", "correction") from None
        return values[-1] if values else None

    def _periods(self):
        return [self.base._period(row["id"]) for row in self.cipher.db.query("SELECT id FROM periods WHERE status='open' ORDER BY start_date,id")]

    @_locked
    def authorize(self, person_id, action, resource_id):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported AP exception action.", "action")
        authority = self.base._authority(person_id)
        kind = RESOURCE_TYPES[action]
        record = self._invoice(authority, resource_id) if kind == "invoice" else self._approval(authority, resource_id) if kind == "approval" else self._supported_bill(authority, resource_id)
        project_id = record["manifest"]["bindings"]["project_id"] if kind == "approval" else record["project_id"]
        duty = "accountant"
        if action == "bill.cancel" and record.get("approval_record_id"):
            duty = "pm"
            approval = self.cipher.approvals.get(record["business_approval_id"])
            if not self.cipher.plugin("people").same_person(authority.login, approval["approver"]):
                raise APRefusal(403, "original_approver_required", "Only the original business approver may withdraw this approved bill.", "person")
        if not authority.allows(project_id, duty):
            raise APRefusal(403, "duty_required", "This exception action requires its current project duty.", "duty")
        return {"personId": authority.person_id, "login": authority.login, "duty": duty,
                "projectId": project_id, "record": record, "authority": authority}

    def _version(self, authority, resource_id, resource_type):
        if resource_type not in ("invoice", "bill", "approval"):
            raise APRefusal(422, "unsupported_resource", "Choose a supported exception record.", "resource")
        record = self._invoice(authority, resource_id) if resource_type == "invoice" else self._approval(authority, resource_id) if resource_type == "approval" else self._supported_bill(authority, resource_id)
        bill = self._supported_bill(authority, record["subject_id"]) if resource_type == "approval" else record if resource_type == "bill" else None
        current = None
        if bill:
            try:
                manifest = self.cipher._manifest(CORRECTION_OPERATION, bill["id"], "accountant")
                current = {"material": material_part(manifest), "governance": manifest.get("governance")}
            except (RuntimeError, ValueError, TypeError, KeyError):
                current = {"available": False}
        private = {"provenance": PROVENANCE, "workspace": self.cipher.db.mode_status(), "personId": authority.person_id,
                   "scope": authority.scope_hash, "kind": resource_type, "record": record,
                   "baseVersion": self.base._version(authority, bill["id"]) if bill else self.intake._version(authority, resource_id, "invoice"),
                   "correction": self._correction(bill["id"]) if bill else None, "current": current,
                   "periods": self.cipher.db.query("SELECT * FROM periods ORDER BY start_date,id"),
                   "approvals": self.cipher.db.query("SELECT * FROM approvals WHERE operation=? AND subject_id=? ORDER BY requested_at,id", (CORRECTION_OPERATION, bill["id"])) if bill else []}
        return "apx1-" + self._sign(private)

    @_locked
    def version(self, person_id, resource_id, resource_type):
        return self._version(self.base._authority(person_id), resource_id, resource_type)

    def _action_list(self, authority, candidates, resource_id):
        actions, blocks = [], []
        for action in candidates:
            try:
                context = self.authorize(authority.person_id, action, resource_id)
                if action == "invoice.reject":
                    self.ap.rejection_preflight(resource_id, reason="Review exception readiness")
                elif action == "invoice.reviewDuplicate":
                    self.ap.duplicate_review_preflight(resource_id, reason="Review exception readiness")
                elif action == "bill.cancel":
                    self.cipher.bills.void_preflight(resource_id, actor=authority.login, reason="Review exception readiness")
                elif action == "bill.prepareCorrection":
                    self.cipher.bills.correction_prepare_preflight(resource_id, "Review exception readiness")
                elif action == "bill.requestCorrection":
                    from .ap_exception_preflight import APExceptionPreflight
                    manifest = self.cipher.check_request_approval(CORRECTION_OPERATION, resource_id, actor_role=context["duty"], requested_by=authority.login)
                    APExceptionPreflight(self.cipher, self, secret=self.secret)._duplicate_correction_request(resource_id, manifest)
                elif action == "bill.approveCorrection":
                    self.cipher.check_bill_correction_grant(resource_id, approver=authority.login, approver_role="accountant")
                elif action == "bill.executeCorrection":
                    self.cipher.check_bill_correction_execution(resource_id, actor=authority.login)
                actions.append(action)
            except APRefusal as exc:
                if exc.status != 403:
                    if exc.code == "duplicate_request":
                        blocks.append({"action": action, "code": exc.code, "message": exc.message, "target": exc.target})
                        continue
                    raise
                blocks.append({"action": action, "code": exc.code, "message": exc.message, "target": exc.target})
            except (RuntimeError, ValueError, TypeError, KeyError):
                blocks.append({"action": action, "code": "exception_not_ready", "message": "Current source facts or duties do not permit this exception action.", "target": RESOURCE_TYPES[action]})
        return actions, blocks

    @_locked
    def invoice_review(self, person_id, invoice_id):
        authority = self.base._authority(person_id)
        inv = self._invoice(authority, invoice_id)
        candidates = []
        if inv["status"] in ("received", "matched"):
            candidates.append("invoice.revise")
        if inv["status"] == "received":
            candidates.append("invoice.reject")
            if inv["possible_duplicate"] and not inv["duplicate_cleared_at"]:
                candidates.append("invoice.reviewDuplicate")
        actions, blocks = self._action_list(authority, candidates, invoice_id)
        linked = self.cipher.db.query("SELECT id,status FROM bills WHERE supplier_invoice_id=? AND status IN ('posted','paid')", (invoice_id,))
        if linked:
            actions = [action for action in actions if action not in ("invoice.revise", "invoice.reject")]
            blocks.append({"code": "posted_bill_requires_correction", "message": "Correct the linked posted bill before revising or rejecting this invoice.", "target": "bill"})
        return {**PROVENANCE, "version": self._version(authority, invoice_id, "invoice"),
                "invoice": self.intake._invoice_value(authority, inv), "availableActions": actions, "blockedReasons": blocks}

    @_locked
    def bill_review(self, person_id, bill_id):
        authority = self.base._authority(person_id)
        bill = self._supported_bill(authority, bill_id)
        correction = self._correction(bill_id)
        candidates = ["bill.cancel"] if bill["status"] in ("draft", "approved") else ["bill.prepareCorrection"] if bill["status"] == "posted" and (not correction or correction["status"] != "pending") else []
        if bill["status"] == "posted" and correction and correction["status"] == "pending":
            candidates.append("bill.requestCorrection")
        actions, blocks = self._action_list(authority, candidates, bill_id)
        summary = None if correction is None else {"id": correction["id"], "correctionId": correction["id"], "status": correction["status"],
            "reason": correction["reason"], "requestedBy": self.base._person(correction["requested_by"]), "requestedAt": correction["requested_at"]}
        return {**PROVENANCE, "version": self._version(authority, bill_id, "bill"), "bill": self.base._bill_value(authority, bill),
                "correction": summary, "correctionPeriods": self._periods(), "availableActions": actions, "blockedReasons": blocks}

    def _effective(self, approval):
        if approval["status"] not in ("pending", "granted"):
            return approval["status"]
        if parse_iso(approval["expires_at"]) <= utcnow():
            return "expired"
        try:
            current = self.cipher._manifest(CORRECTION_OPERATION, approval["subject_id"], "accountant")
            if material_hash(current) != approval["material_hash"] or current.get("governance") != approval["manifest"].get("governance"):
                return "stale"
        except (RuntimeError, ValueError, TypeError, KeyError):
            return "stale"
        return approval["status"]

    def _approval_value(self, authority, approval):
        bill = self._supported_bill(authority, approval["subject_id"])
        bound = approval["manifest"]["bindings"]
        return {"id": approval["id"], "approvalId": approval["id"], "version": self._version(authority, approval["id"], "approval"),
                "projectId": bill["project_id"], "projectName": self.intake._project(authority, bill["project_id"])["name"],
                "billId": bill["id"], "sequence": bill["sequence"], "supplierName": self.cipher.party(bill["supplier_id"])["name"],
                "status": approval["status"], "effectiveStatus": self._effective(approval), "requestedBy": self.base._person(approval["requested_by"]),
                "approvedBy": self.base._person(approval["approver"]), "requestedAt": approval["requested_at"], "approvedAt": approval["granted_at"],
                "expiresAt": approval["expires_at"], "amountDueCents": _money(approval["manifest"]["amounts"]["amount_due"]),
                "correctionId": bound["request"]["id"], "reason": bound["reason"]}

    @_locked
    def packet(self, person_id, approval_id):
        authority = self.base._authority(person_id)
        approval = self._approval(authority, approval_id)
        bill = self._supported_bill(authority, approval["subject_id"])
        value = self._approval_value(authority, approval)
        bound = approval["manifest"]["bindings"]
        correction = self._correction(bill["id"])
        before = {"billStatus": bound["bill_status"], "amountDueCents": value["amountDueCents"], "correctionId": value["correctionId"], "reason": bound["reason"]}
        current = {"billStatus": bill["status"], "amountDueCents": _money(bill["amount_due"]),
                   "correctionId": correction["id"] if correction else None, "reason": correction["reason"] if correction else None}
        candidates = ["bill.approveCorrection"] if value["effectiveStatus"] == "pending" else ["bill.executeCorrection"] if value["effectiveStatus"] == "granted" else []
        actions, blocks = self._action_list(authority, candidates, approval_id)
        return {**PROVENANCE, **value, "bill": self.base._bill_value(authority, bill), "boundFacts": before, "currentFacts": current,
                "changes": [{"field": key, "before": before[key], "after": current[key]} for key in before if before[key] != current[key]],
                "effect": {"billStatus": "corrected", "externalAccounting": "unavailable", "payment": "not_started"},
                "correctionPeriods": self._periods(), "availableActions": actions, "blockedReasons": blocks}

    @_locked
    def read(self, person_id, collection="correction-approvals", *, project_id=None, status=None, search=None, top=50, cursor=None):
        if collection != "correction-approvals" or type(top) is not int or not 1 <= top <= 100:
            raise APRefusal(422, "invalid_query", "Choose correction approvals and a page size from one through 100.", "collection")
        if status is not None and status not in APPROVAL_STATUSES:
            raise APRefusal(422, "invalid_query", "Choose a supported correction approval status.", "status")
        if search is not None and (type(search) is not str or len(search) > 200 or any(ord(char) < 32 for char in search)):
            raise APRefusal(422, "invalid_query", "Use search text of at most 200 characters.", "search")
        if project_id is not None and (type(project_id) is not str or not project_id or len(project_id) > 200
                or project_id != project_id.strip() or any(ord(char) < 32 for char in project_id)):
            raise APRefusal(422, "invalid_query", "Choose a valid practice project ID.", "projectId")
        if cursor is not None and (type(cursor) is not str or not cursor or len(cursor) > 2048):
            raise APRefusal(422, "invalid_query", "Choose a valid practice paging cursor.", "cursor")
        authority = self.base._authority(person_id)
        if project_id is not None:
            self.intake._project(authority, project_id)
        projects = (project_id,) if project_id else authority.project_ids
        pairs = []
        for project in projects:
            for row in self.cipher.db.query("SELECT a.id,a.requested_at FROM approvals a JOIN bills b ON b.id=a.subject_id AND a.subject_type='bill' JOIN commitments c ON c.id=b.commitment_id WHERE a.operation=? AND c.project_id=? ORDER BY a.requested_at,a.id", (CORRECTION_OPERATION, project)):
                pairs.append(((row["requested_at"], row["id"]), self._approval_value(authority, self._approval(authority, row["id"]))))
        search = search.strip().casefold() if search else None
        if status:
            pairs = [pair for pair in pairs if pair[1]["status"] == status]
        if search:
            pairs = [pair for pair in pairs if any(search in str(pair[1][key]).casefold() for key in ("supplierName", "projectName", "reason"))]
        pairs.sort(key=lambda pair: pair[0])
        binding = self._sign({"person": authority.person_id, "scope": authority.scope_hash, "project": project_id,
                              "status": status, "search": search, "top": top, "collection": collection})
        last = self.base._cursor_key(cursor, binding)
        selected = [pair for pair in pairs if last is None or pair[0] > last]
        page = selected[:top]
        values = [pair[1] for pair in pairs]
        return {**PROVENANCE, "collection": collection, "projectId": project_id, "value": [pair[1] for pair in page], "count": len(values),
                "nextCursor": self.base._token({"v": 1, "binding": binding, "last": list(page[-1][0])}) if len(selected) > top else None,
                "facets": {"statuses": [{"value": item, "count": sum(value["status"] == item for value in values)} for item in sorted({value["status"] for value in values})]}, "totals": {}}
