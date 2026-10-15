"""Pure fixed owner-billing reviews over actual scoped native source checks.

Review creates no source, approval, command, receipt, journal or delivery. The
same server-owned native plans and current duties are checked before effects.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import hmac
import json

from .ap_contract import APRefusal
from .ar_sessions import ARIdentityRefusal
from .ar_wire import ACTIONS, ACTION_ROUTES, PROVENANCE, WireRefusal, decode_action_body
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash, material_part
from .core.ids import canonical_json, parse_iso, utcnow
from .core.money import money

RESOURCE_TYPES = {route.action: route.resource_type for route in ACTION_ROUTES}


class ARPreflight:
    def __init__(self, cipher, contract, *, secret):
        if type(secret) is not bytes or len(secret) < 32 or contract.cipher is not cipher:
            raise ValueError("AR review requires one owned scoped runtime and private server key")
        self.cipher, self.contract, self.secret = cipher, contract, secret
        self.domain = cipher.plugin("owner_billing")

    @staticmethod
    def _body(action, body, *, effect=False):
        if type(body) is not dict:
            raise APRefusal(422, "invalid_body", "Use one exact owner-billing object.", "body")
        try:
            decoded = decode_action_body(action, json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(), effect=effect)
            return {key: value for key, value in decoded.items() if key != "fingerprint"}
        except WireRefusal as exc:
            raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
        except (TypeError, ValueError, RecursionError):
            raise APRefusal(422, "invalid_body", "Use the fixed exact values for this owner-billing action.", "body") from None

    @staticmethod
    def _effects():
        return {"createsDraft": False, "createsApproval": False, "grantsApproval": False,
                "approvalStatus": None, "billStatus": None, "workingLedgerJournalDelta": 0,
                "arReceivableDeltaCents": 0, "retainedARDeltaCents": 0, "revenueDeltaCents": 0,
                "journalPreview": [], "syntheticSendDelta": 0, "mailSinkOnly": True,
                "externalAccounting": "unavailable", "quickBooksAccepted": False,
                "externalDelivery": False, "externalSettlement": False}

    @staticmethod
    def _check(code, message, target):
        return {"code": code, "status": "passed", "message": message, "target": target, "fix": None}

    @staticmethod
    def _refusal(exc, target):
        if isinstance(exc, APRefusal):
            return exc
        if isinstance(exc, ARIdentityRefusal):
            return APRefusal(exc.status, exc.code, exc.message, exc.target)
        if isinstance(exc, ApprovalExpired):
            return APRefusal(423, "owner_authorization_expired", "This owner-billing authorization expired. Request fresh review.", "approval")
        if isinstance(exc, StaleApprovalError):
            return APRefusal(412, "owner_source_changed", "The original owner source, terms or current duty changed. Review again.", target)
        if isinstance(exc, PermissionError):
            return APRefusal(403, "actual_ar_duty_required", "This step requires the person's own current project duty.", "duty")
        if isinstance(exc, ApprovalError):
            return APRefusal(409, "owner_action_unavailable", "The current owned source or original authorization does not permit this step.", target)
        return APRefusal(423, "owner_source_unavailable", "This owner-billing source cannot currently be verified.", target)

    def _service(self, name, *args, **kwargs):
        check = getattr(self.cipher, name, None)
        if not callable(check):
            raise ApprovalError("The required pure native owner-billing check is unavailable")
        return check(*args, **kwargs)

    def _scoped_revision(self, context, revision_id):
        row = self.cipher.db.one("SELECT d.project_id FROM document_revisions r JOIN documents d ON d.id=r.document_id WHERE r.id=?", (revision_id,))
        if row is None or row["project_id"] != context["projectId"] or row["project_id"] not in context["authority"].project_ids:
            raise APRefusal(404, "not_found", "The source is unavailable in this AR session.", "record")

    def _duplicates(self, context, bill_id, operation, manifest):
        for proof in self.domain.approval_inventory(project_ids=(context["projectId"],)):
            approval = proof["approval"]
            if (approval["subject_id"] != bill_id or approval["operation"] != operation
                    or approval["status"] not in ("pending", "granted") or parse_iso(approval["expires_at"]) <= utcnow()):
                continue
            if (approval["material_hash"] == material_hash(manifest)
                    and canonical_json(approval["manifest"].get("governance")) == canonical_json(manifest.get("governance"))):
                raise APRefusal(409, "duplicate_request", "This owner bill already has this current review request.", "approval")

    @staticmethod
    def _preview(source=None, plan=None, manifest=None):
        if source is None:
            calculation, period = plan["calculation"], plan["period"]
            invoice_date, date_policy, due_date = plan["invoiceDate"], plan["datePolicy"], None
        else:
            calculation, period = source["calculation"], source["record"]["period"]
            invoice_date, date_policy = source["record"]["invoiceDate"], source["record"]["datePolicy"]
            due_date = source["bill"].get("due_date")
        public = {"calculation": {key: value for key, value in calculation.items() if key != "calculationHash"},
                  "period": {key: period[key] for key in ("id", "name", "startDate", "endDate")},
                  "invoiceDate": invoice_date, "dueDate": due_date, "datePolicy": date_policy, "delivery": None}
        if manifest is not None and manifest["operation"] == "prime_bill.send":
            bindings = manifest["bindings"]
            public["delivery"] = {"channel": bindings["channel"], "recipients": list(bindings["recipients"]),
                "amountDueCents": int(money(manifest["amounts"]["amount_due"])*100),
                "balanceDueCents": int(money(bindings["balance_due"])*100)}
        return public

    def _prospect(self, context, action, resource_id, typed):
        actor = context["login"]
        effects, manifest, approval_clock = self._effects(), None, None
        if action == "ownerBill.prepare":
            for field in ("claimRevisionId", "reviewRevisionId"):
                self._scoped_revision(context, typed[field])
            plan = self.domain.prepare_preflight(resource_id, typed, actor=actor)
            source_facts = {key: plan[key] for key in ("basis", "claim", "review", "period", "previousSourceId", "previousSourceHash")}
            preview = self._preview(plan=plan)
            effects.update(createsDraft=True, billStatus="draft")
            message = "The complete declared owner SOV and separate claimed/reviewed sources produce one draft. No receivable or journal is created."
        else:
            if action == "ownerBill.requestApproval":
                checked = self._service("check_prime_bill_request", resource_id, requested_by=actor, actor_role="accountant")
                manifest = checked["manifest"]
                self._duplicates(context, resource_id, "prime_bill.approve", manifest)
                effects.update(createsApproval=True, approvalStatus="pending", billStatus="draft")
                message = "Request independent accounting review of this exact owner source and working-ledger preview."
            elif action == "ownerBill.approve":
                checked = self._service("check_prime_bill_grant", resource_id, approver=actor, approver_role=context["operationRole"])
                manifest = checked["manifest"]
                effects.update(grantsApproval=True, approvalStatus="granted", billStatus="draft")
                message = "Grant the original owner-billing authorization without posting. A different actual accounting person posts under this same grant."
            elif action == "ownerBill.post":
                checked = self._service("check_prime_bill_post", resource_id, actor=actor)
                manifest = checked["manifest"]
                calc = checked["source"]["calculation"]
                effects.update(approvalStatus="consumed", billStatus="posted", workingLedgerJournalDelta=1,
                    arReceivableDeltaCents=calc["amountDueCents"], retainedARDeltaCents=calc["retainageThisPeriodCents"],
                    revenueDeltaCents=calc["revenueThisPeriodCents"], journalPreview=calc["journalPreview"])
                message = "Consume the original independent business grant and post one exact working-ledger journal in its original period."
            elif action == "ownerBill.requestSend":
                checked = self._service("check_prime_bill_send_request", resource_id, requested_by=actor, actor_role=context["operationRole"])
                manifest = checked["manifest"]
                self._duplicates(context, resource_id, "prime_bill.send", manifest)
                effects.update(createsApproval=True, approvalStatus="pending", billStatus="posted")
                message = "Request separate review of this exact current balance and synthetic mail-sink message."
            elif action == "ownerBill.approveSend":
                checked = self._service("check_prime_bill_send_grant", resource_id, approver=actor, approver_role=context["operationRole"])
                manifest = checked["manifest"]
                effects.update(grantsApproval=True, approvalStatus="granted", billStatus="posted")
                message = "A different current PM or accountant authorizes only this exact synthetic send. No receivable or journal changes."
            else:
                checked = self._service("check_prime_bill_send_execution", resource_id, actor=actor)
                manifest = checked["manifest"]
                effects.update(approvalStatus="consumed", billStatus="sent", syntheticSendDelta=1)
                message = "Record one exact message in the synthetic mail sink. This does not prove external delivery or customer receipt."
            plan = {key: value for key, value in checked.items() if key not in ("manifest", "governors")}
            source_facts = {"source": checked["source"]}
            if "approval" in checked:
                approval = checked["approval"]
                source_facts["approval"] = approval
                source_facts["originalApproval"] = self.domain.approval_proof(approval["id"])
                approval_clock = {"expiresAt": approval["expires_at"], "originalExpiresAt": approval["manifest"]["expires_at"]}
            if "grant" in checked:
                source_facts["grant"] = checked["grant"]
            if "posting" in checked:
                source_facts["posting"] = checked["posting"]
            preview = self._preview(source=checked["source"], manifest=manifest)
        return {"plan": plan, "sourceFacts": source_facts, "manifest": manifest, "preview": preview,
                "safeEffects": effects, "approvalClock": approval_clock,
                "checks": [self._check("owned_owner_source_ready", message, RESOURCE_TYPES[action])], "changes": []}

    def _evaluate(self, person_id, action, resource_id, typed):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported owner-billing action.", "action")
        # Minimal references and current actual project duty precede all private
        # source/approval facts, original outcomes, counts and effect previews.
        context = self.contract.authorize(person_id, action, resource_id)
        duty = next(route.duty for route in ACTION_ROUTES if route.action == action)
        operation_role = "accountant" if action == "ownerBill.requestApproval" else context["authority"].operation_role(context["projectId"], duty)
        context["operationRole"], context["typed"] = operation_role, typed
        version = self.contract.version(person_id, resource_id, RESOURCE_TYPES[action])
        effects, checks, changes, refusal, prospect = self._effects(), [], [], None, None
        try:
            self.cipher.db.require_practice_mode()
            self.cipher.db.require_write_authority()
            if not self.cipher.db.in_memory:
                raise ApprovalError("This first owner-billing entry requires disposable memory")
            prospect = self._prospect(context, action, resource_id, typed)
            effects, checks, changes = prospect["safeEffects"], prospect["checks"], prospect["changes"]
            context.update(plan=prospect["plan"], sourceFacts=prospect["sourceFacts"], manifest=prospect["manifest"])
        except Exception as exc:
            if isinstance(exc, APRefusal) and exc.status == 404:
                raise
            refusal = self._refusal(exc, RESOURCE_TYPES[action])
            checks.append({"code": refusal.code, "status": "blocked", "target": refusal.target,
                           "message": refusal.message, "fix": "Refresh the owned source and original authorization before review."})
        fingerprint = None
        if refusal is None:
            manifest = prospect["manifest"]
            material = {"provenance": PROVENANCE, "workspace": self.cipher.db.mode_status(),
                "authority": self.cipher.db.authority_status(), "personId": context["personId"], "login": context["login"],
                "duty": context["duty"], "operationRole": operation_role, "scopeHash": context["authority"].scope_hash,
                "action": action, "resourceId": resource_id, "version": version, "typed": typed,
                "plan": prospect["plan"], "sourceFacts": prospect["sourceFacts"],
                "material": material_part(manifest) if manifest else None,
                "governance": manifest.get("governance") if manifest else None,
                "approvalClock": prospect["approvalClock"], "calculationDate": self.cipher.receivables._today().isoformat(),
                "effects": effects, "preview": prospect["preview"]}
            digest = hmac.new(self.secret, canonical_json(material).encode(), sha256).digest()
            fingerprint = "arpf1." + base64.urlsafe_b64encode(digest).decode().rstrip("=")
        review = {**PROVENANCE, "action": action, "resourceId": resource_id, "resourceVersion": version,
            "version": version, "allowed": refusal is None, "checks": checks, "changes": changes,
            "safeEffects": effects, "fingerprint": fingerprint}
        if refusal is None:
            review["preview"] = prospect["preview"]
        return context, review, refusal

    def review(self, person_id, action, resource_id, body):
        typed = self._body(action, body)
        with self.cipher.db._lock:
            return self._evaluate(person_id, action, resource_id, typed)[1]

    def verify(self, person_id, action, resource_id, body, if_match):
        typed = self._body(action, body, effect=True)
        with self.cipher.db._lock:
            context, review, refusal = self._evaluate(person_id, action, resource_id, typed)
            if refusal:
                raise refusal
            if type(if_match) is not str or if_match != review["resourceVersion"]:
                raise APRefusal(412, "record_changed", "This owner-billing record changed. Review it again.", "If-Match")
            fingerprint = body.get("fingerprint")
            if type(fingerprint) is not str or not fingerprint.isascii() or not hmac.compare_digest(fingerprint, review["fingerprint"]):
                raise APRefusal(412, "preflight_changed", "The reviewed owner source or current duty changed. Review this step again.", "fingerprint")
            context["review"] = review
            return context
