"""Pure, exact and scoped reviews for AP exception recovery and corrections."""
from __future__ import annotations

import base64
import hmac
from decimal import Decimal
from hashlib import sha256

from .ap_contract import APRefusal
from .ap_exception_contract import ACTIONS, RESOURCE_TYPES, CORRECTION_OPERATION
from .ap_intake_preflight import APIntakePreflight
from .ap_preflight import _cents, _locked
from .core.approvals import ApprovalExpired, material_hash, material_part
from .core.ids import canonical_json, utcnow


def correction_approval_proof(cipher, approval_id):
    return cipher.bills.correction_approval_proof(approval_id)


class APExceptionPreflight(APIntakePreflight):
    def __init__(self, cipher, contract, *, secret):
        if type(secret) is not bytes or len(secret) < 32 or contract.cipher is not cipher:
            raise ValueError("Exception reviews require their owned AP workspace and private server key.")
        self.c, self.contract, self.secret = cipher, contract, secret
        self.ap, self.now = cipher.plugin("ap_intake"), utcnow

    def authorize(self, person_id, action, resource_id):
        return self.contract.authorize(person_id, action, resource_id)

    @staticmethod
    def _safe_refusal(exc, target):
        refusal = APIntakePreflight._safe_refusal(exc, target)
        if refusal.code == "approval_expired":
            return APRefusal(423, refusal.code, "The correction authorization expired. Request fresh approval.", target)
        if refusal.code == "approval_stale":
            return APRefusal(412, refusal.code, "The approved correction facts or authority changed. Request fresh approval.", target)
        if refusal.code == "review_unavailable":
            return APRefusal(500, refusal.code, "The current AP exception review could not be verified.", target)
        if refusal.code == "period_locked":
            return APRefusal(423, refusal.code, "The selected correction period is closed or locked.", "periodId")
        if refusal.code == "duty_refused":
            return APRefusal(403, refusal.code, "This person cannot perform this exception action with their current authority.", "duty")
        return refusal

    @classmethod
    def _body(cls, action, body=None, *, action_body=False):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported AP exception action.", "action")
        if body is None:
            body = {}
        fields = ({"reason", "invoiceNumber", "invoiceDate", "amountCents", "evidenceRevisionId"} if action == "invoice.revise" else
                  {"reason"} if action in ("invoice.reject", "invoice.reviewDuplicate", "bill.cancel", "bill.prepareCorrection") else
                  {"periodId"} if action == "bill.executeCorrection" else set())
        allowed = fields | ({"fingerprint"} if action_body else set())
        if type(body) is not dict or set(body) - allowed or fields - set(body):
            raise APRefusal(422, "invalid_body", "Send exactly the named JSON fields for this exception action.", "body")
        typed = {}
        if "reason" in fields:
            typed["reason"] = cls._text(body["reason"], "reason", maximum=500)
        if action == "invoice.revise":
            receipt = super()._body("invoice.receive", {key: body[key] for key in ("invoiceNumber", "invoiceDate", "amountCents", "evidenceRevisionId")})
            typed.update(receipt)
        if action == "bill.executeCorrection":
            typed["periodId"] = cls._text(body["periodId"], "periodId")
        return typed

    def _duplicate_correction_request(self, bill_id, manifest):
        for row in self.c.db.query("SELECT id FROM approvals WHERE operation=? AND subject_id=? AND status IN ('pending','granted') ORDER BY requested_at,id", (CORRECTION_OPERATION, bill_id)):
            correction_approval_proof(self.c, row["id"])
            approval = self.c.approvals.get(row["id"])
            try:
                self._deadline(approval)
            except ApprovalExpired:
                continue
            if material_hash(manifest) == approval["material_hash"] and manifest.get("governance") == approval["manifest"].get("governance"):
                raise APRefusal(409, "duplicate_request", "This bill already has a current correction approval request.", row["id"])

    @staticmethod
    def _effects():
        return {"billStatus": None, "invoiceStatus": None, "approvalStatus": None, "workingLedgerJournalDelta": 0,
                "apPayableDeltaCents": 0, "journalPreview": [], "externalAccounting": "unavailable", "payment": "not_started",
                "duplicateReviewed": False, "requiresNewMatch": False, "invalidatedApprovalCount": 0}

    def _journal_preview(self, journals):
        result = []
        for journal in journals:
            lines = []
            for line in journal["lines"]:
                code = line.get("account", line.get("account_code"))
                account = self.c.db.one("SELECT name FROM accounts WHERE code=?", (code,))
                lines.append({"account": code, "accountName": account["name"] if account else None,
                              "projectId": line.get("project_id"), "partyId": line.get("party_id"), "memo": line.get("memo", ""),
                              "debitCents": _cents(line.get("debit", "0")), "creditCents": _cents(line.get("credit", "0"))})
            result.append({"periodId": journal["period_id"], "description": journal["description"],
                           "sourceVersion": journal.get("source_version", "1"), "lines": lines})
        return result

    def _evaluate(self, person_id, action, resource_id, typed):
        context = self.authorize(person_id, action, resource_id)
        version = self.contract.version(person_id, resource_id, RESOURCE_TYPES[action])
        context["typed"] = typed
        record = context["record"]
        approval = record if RESOURCE_TYPES[action] == "approval" else None
        checks = [self._check("person_authorized", "passed", "person", "The registered person holds the required current project duty.")]
        effects, changes, plan, manifest, refusal = self._effects(), [], None, None, None
        try:
            self.c.db.require_practice_mode()
            if action == "invoice.revise":
                evidence = self.contract.intake.evidence(person_id, typed["evidenceRevisionId"])
                if evidence["project_id"] != context["projectId"]:
                    raise APRefusal(404, "not_found", "This source is not available in the current project scope.", "evidenceRevisionId")
                if not evidence["is_current"]:
                    raise APRefusal(423, "evidence_stale", "Choose the current supplier invoice evidence revision.", "evidenceRevisionId")
                params = {"reason": typed["reason"], "invoice_number": typed["invoiceNumber"], "invoice_date": typed["invoiceDate"],
                          "amount": Decimal(typed["amountCents"]) / 100, "evidence_hash": evidence["content_hash"]}
                plan = self.ap.revision_preflight(resource_id, **params)
                context.update(params=params, evidence=evidence)
                effects.update(invoiceStatus="received", amountCents=typed["amountCents"], requiresNewMatch=True,
                               invalidatedApprovalCount=len(plan.get("invalidated_approval_ids", [])))
                for key, before, after in (("invoiceNumber", record["invoice_number"], typed["invoiceNumber"]),
                                          ("invoiceDate", record["invoice_date"], typed["invoiceDate"]),
                                          ("amountCents", _cents(record["amount"]), typed["amountCents"]),
                                          ("evidenceRevisionId", record["evidence_revision_id"], typed["evidenceRevisionId"])):
                    if before != after:
                        changes.append({"field": key, "before": before, "after": after})
            elif action == "invoice.reject":
                plan = self.ap.rejection_preflight(resource_id, reason=typed["reason"])
                effects.update(invoiceStatus="rejected", amountCents=_cents(record["amount"]),
                               invalidatedApprovalCount=len(plan.get("invalidated_approval_ids", [])))
            elif action == "invoice.reviewDuplicate":
                plan = self.ap.duplicate_review_preflight(resource_id, reason=typed["reason"])
                effects.update(invoiceStatus=record["status"], amountCents=_cents(record["amount"]), duplicateReviewed=True)
            elif action == "bill.cancel":
                plan = self.c.bills.void_preflight(resource_id, actor=context["login"], reason=typed["reason"])
                effects.update(billStatus="void", amountDueCents=_cents(record["amount_due"]),
                               invalidatedApprovalCount=len(plan.get("open_approval_ids", [])))
            elif action == "bill.prepareCorrection":
                plan = self.c.bills.correction_prepare_preflight(resource_id, typed["reason"])
                effects.update(billStatus=record["status"], amountDueCents=_cents(record["amount_due"]))
            elif action == "bill.requestCorrection":
                manifest = self.c.check_request_approval(CORRECTION_OPERATION, resource_id, actor_role=context["duty"], requested_by=context["login"])
                self._duplicate_correction_request(resource_id, manifest)
                effects.update(billStatus=record["status"], approvalStatus="pending", amountDueCents=_cents(record["amount_due"]))
            else:
                correction_approval_proof(self.c, resource_id)
                self._deadline(approval)
                if action == "bill.approveCorrection":
                    checked = self.c.check_bill_correction_grant(resource_id, approver=context["login"], approver_role=context["duty"])
                    effects.update(billStatus="posted", approvalStatus="granted", amountDueCents=_cents(approval["manifest"]["amounts"]["amount_due"]))
                else:
                    checked = self.c.check_bill_correction_execution(resource_id, actor=context["login"], period_id=typed["periodId"])
                    plan = checked.get("plan", checked)
                    journals = checked.get("journal_preview", plan.get("journal_preview", []))
                    effects.update(billStatus="corrected", approvalStatus="consumed", workingLedgerJournalDelta=len(journals),
                                   apPayableDeltaCents=-_cents(approval["manifest"]["amounts"]["amount_due"]),
                                   amountDueCents=_cents(approval["manifest"]["amounts"]["amount_due"]), journalPreview=self._journal_preview(journals))
                manifest = checked["manifest"]
            checks.append(self._check("exception_ready", "passed", "approval" if approval else RESOURCE_TYPES[action],
                                      "Current source facts and duties permit the stated exception effect. Official accounting and payments remain unavailable."))
        except Exception as exc:
            if isinstance(exc, APRefusal) and exc.status == 404:
                raise
            refusal = self._safe_refusal(exc, "approval" if approval else RESOURCE_TYPES[action])
            checks.append(self._check(refusal.code, "blocked", refusal.target, refusal.message, "Refresh and review current source facts and duties."))
            effects = self._effects()
        context.update(plan=plan, manifest=manifest)
        if approval:
            context["approval"] = approval
        fingerprint = None
        if refusal is None:
            facts = {"workspace": self.c.db.mode_status(), "personId": context["personId"], "login": context["login"], "duty": context["duty"],
                     "scope": context["authority"].scope_hash, "action": action, "resourceId": resource_id, "version": version,
                     "body": typed, "plan": plan, "effects": effects, "approval": approval,
                     "material": material_part(manifest) if manifest else None, "governance": manifest.get("governance") if manifest else None}
            fingerprint = "xpf1." + base64.urlsafe_b64encode(hmac.new(self.secret, canonical_json(facts).encode(), sha256).digest()).decode("ascii").rstrip("=")
        return context, {"action": action, "resourceId": resource_id, "resourceVersion": version, "version": version,
                         "allowed": refusal is None, "checks": checks, "changes": changes, "safeEffects": effects, "fingerprint": fingerprint}, refusal
