"""Pure issued-source RFI response and distribution reviews over native source checks.

Review creates no RFI, response, distribution, approval, command or receipt. The
same server-owned native plans and current duties are checked before effects.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import hmac
import json

from .ap_contract import APRefusal
from .rfi_sessions import RFIIdentityRefusal
from .rfi_wire import ACTIONS, ACTION_ROUTES, PROVENANCE, WireRefusal, decode_action_body
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_part
from .core.ids import canonical_json, utcnow

RESOURCE_TYPES = {route.action: route.resource_type for route in ACTION_ROUTES}


class RFIPreflight:
    def __init__(self, cipher, contract, *, secret):
        if type(secret) is not bytes or len(secret) < 32 or contract.cipher is not cipher:
            raise ValueError("RFI review requires one owned scoped runtime and private server key")
        self.cipher, self.contract, self.secret = cipher, contract, secret
        self.domain = cipher.plugin("rfi_controls")

    @staticmethod
    def _body(action, body, *, effect=False):
        if type(body) is not dict:
            raise APRefusal(422, "invalid_body", "Use one exact RFI object.", "body")
        try:
            decoded = decode_action_body(action, json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(), effect=effect)
            return {key: value for key, value in decoded.items() if key != "fingerprint"}
        except WireRefusal as exc:
            raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
        except (TypeError, ValueError, RecursionError):
            raise APRefusal(422, "invalid_body", "Use the fixed exact values for this RFI action.", "body") from None

    @staticmethod
    def _effects():
        return {"rfisDelta": 0, "rfiLinksDelta": 0, "drawingReferencesDelta": 0, "rfiSourcesDelta": 0,
                "responseRevisionsDelta": 0, "distributionRevisionsDelta": 0, "approvalSourcesDelta": 0,
                "approvalsDelta": 0, "syntheticDistributionsDelta": 0, "invalidatedApprovalsDelta": 0,
                "approvalStatus": None, "rfiStatus": None, "journalDelta": 0,
                "changeDraftDelta": 0, "changeExecutionDelta": 0, "commitmentDelta": 0,
                "contractValueDeltaCents": 0, "budgetDeltaCents": 0, "scheduleBaselineDeltaDays": 0,
                "externalDistribution": False, "engineeringCertification": False,
                "adoptsPotentialImpacts": False, "mailSinkOnly": True}

    @staticmethod
    def _check(code, message, target):
        return {"code": code, "status": "passed", "message": message, "target": target, "fix": None}

    @staticmethod
    def _refusal(exc, target):
        if isinstance(exc, APRefusal):
            return exc
        if isinstance(exc, RFIIdentityRefusal):
            return APRefusal(exc.status, exc.code, exc.message, exc.target)
        if isinstance(exc, ApprovalExpired):
            return APRefusal(423, "rfi_authorization_expired", "This RFI authorization expired. Request fresh review.", "approval")
        if isinstance(exc, StaleApprovalError):
            return APRefusal(412, "rfi_source_changed", "The original RFI citations, response, recipients or current project duty changed. Review again.", target)
        if isinstance(exc, PermissionError):
            return APRefusal(403, "actual_rfi_pm_required", "This step requires the person's own current project duty.", "duty")
        if isinstance(exc, ApprovalError):
            return APRefusal(409, "rfi_action_unavailable", "The current owned source or original authorization does not permit this step.", target)
        return APRefusal(423, "rfi_source_unavailable", "This RFI source cannot currently be verified.", target)

    def _prospect(self, context, action, resource_id, typed):
        actor = context["login"]
        effects, manifest, approval_clock = self._effects(), None, None
        approval, reviewed_context = None, None
        if action == "rfi.create":
            checked = self.domain.create_preflight(resource_id, typed, actor=actor)
            effects.update(rfisDelta=1, rfiLinksDelta=len(typed["drawingRevisionIds"])+len(typed["documentRevisionIds"]),
                           drawingReferencesDelta=len(typed["drawingRevisionIds"]), rfiSourcesDelta=1, rfiStatus="open")
            message = "Record one authored question and its exact issued drawing and supporting citations. No official response or financial change occurs."
        elif action == "rfi.draftResponse":
            checked = self.domain.response_preflight(resource_id, typed, actor=actor)
            effects.update(responseRevisionsDelta=1, rfiStatus="open")
            message = "Record the proposed response and informational impacts. This does not answer the RFI or adopt a cost or schedule change."
        elif action == "rfi.setDistribution":
            checked = self.domain.distribution_list_preflight(resource_id, typed, actor=actor)
            effects.update(distributionRevisionsDelta=1, rfiStatus="answered")
            message = "Record the fixed synthetic recipient list. Separate independent review is required before a local mail-sink distribution."
        elif action in ("rfi.requestResponse", "rfi.requestDistribution"):
            method = self.domain.response_request_preflight if action == "rfi.requestResponse" else self.domain.distribution_request_preflight
            checked = method(resource_id, actor=actor)
            effects.update(approvalsDelta=1, approvalSourcesDelta=1, approvalStatus="pending")
            message = "Request a different actual project PM to review the exact original citations, current source disclosures and proposed response or recipient list."
        elif action in ("rfi.approveResponse", "rfi.approveDistribution"):
            checked = self.domain.grant_preflight(resource_id, actor=actor)
            effects.update(approvalStatus="granted")
            message = "Grant independent PM review of this unchanged packet. No official answer or distribution is created by this grant."
        else:
            checked = self.domain.execution_preflight(resource_id, actor=actor)
            effects.update(approvalStatus="consumed")
            if action == "rfi.applyResponse":
                effects.update(rfiStatus="answered")
                message = "Apply the original independent grant and record the exact official response. Potential impacts remain informational."
            else:
                effects.update(rfiStatus="answered", syntheticDistributionsDelta=1)
                message = "Consume the original distribution grant and record one fixed local synthetic mail-sink distribution. No outside delivery occurs."
        source = checked["source"]
        native = source.get("native", {})
        if action in ("rfi.draftResponse", "rfi.setDistribution"):
            effects["invalidatedApprovalsDelta"] = sum(proof["record"]["status"] in ("pending", "granted") for proof in source["approvals"])
        manifest = checked.get("manifest")
        if "approval" in checked:
            approval = checked["approval"]
            row = approval["record"]
            reviewed_context = approval["source"]["record"]["context"]
            approval_clock = {"expiresAt": row["expires_at"], "originalExpiresAt": row["manifest"]["expires_at"]}
        # Preserve complete private current rights separately from original sealed
        # rights. Mutable permission explanations cannot disappear behind a hash.
        if manifest is not None:
            operation = manifest["operation"]
            current_context, _digest = self.domain._review_context(source, operation)
            current_rights = current_context["rights"]
        elif action == "rfi.create":
            current_rights = source["rights"]
        else:
            from .domain.owned_sources import document_rights_proof
            ids = {p["document"]["id"] for p in source["documents"]} | {p["evidence"]["document"]["id"] for p in source["drawings"]}
            use = "distribution" if action == "rfi.setDistribution" else "project_use"
            current_rights = [document_rights_proof(self.cipher, context["projectId"], identifier, use) for identifier in sorted(ids)]
        source_facts = {"source": source, "currentRights": current_rights}
        if approval is not None:
            source_facts["originalApproval"] = approval
        plan = {key: value for key, value in checked.items() if key not in ("manifest", "governors")}
        supplied = checked.get("nativeInput", {})
        response_text = supplied.get("response_text", native.get("draft_response") if native.get("status") == "open" else native.get("response"))
        cost = supplied.get("cost_impact", native.get("draft_cost_impact") if native.get("status") == "open" else native.get("cost_impact"))
        days = supplied.get("schedule_impact_days", native.get("draft_schedule_impact_days") if native.get("status") == "open" else native.get("schedule_impact_days"))
        recipients = supplied.get("recipients")
        if recipients is None and native.get("distribution_recipients_json"):
            recipients = json.loads(native["distribution_recipients_json"])
        preview = {"source": self.contract.source_disclosure(source, reviewed_context=reviewed_context),
                   "subject": supplied.get("subject", native.get("subject")), "question": supplied.get("question", native.get("question")),
                   "responseText": response_text, **self.contract.impact(cost, days),
                   "recipients": recipients or [], "approvalId": approval["record"]["id"] if approval is not None else None}
        return {"plan": plan, "sourceFacts": source_facts, "manifest": manifest, "preview": preview,
                "safeEffects": effects, "approvalClock": approval_clock,
                "checks": [self._check("owned_rfi_review_ready", message, RESOURCE_TYPES[action])], "changes": []}

    def _evaluate(self, person_id, action, resource_id, typed):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported RFI action.", "action")
        # Minimal references and current actual project duty precede all private
        # source/approval facts, original outcomes, counts and effect previews.
        context = self.contract.authorize(person_id, action, resource_id)
        duty = next(route.duty for route in ACTION_ROUTES if route.action == action)
        operation_role = context["authority"].operation_role(context["projectId"], duty)
        context["operationRole"], context["typed"] = operation_role, typed
        version = self.contract.version(person_id, resource_id, RESOURCE_TYPES[action])
        effects, checks, changes, refusal, prospect = self._effects(), [], [], None, None
        try:
            self.cipher.db.require_practice_mode()
            self.cipher.db.require_write_authority()
            if not self.cipher.db.in_memory:
                raise ApprovalError("This first rfi entry requires disposable memory")
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
                "approvalClock": prospect["approvalClock"], "evaluationDate": utcnow().date().isoformat(),
                "effects": effects, "preview": prospect["preview"]}
            digest = hmac.new(self.secret, canonical_json(material).encode(), sha256).digest()
            fingerprint = "rfipf1." + base64.urlsafe_b64encode(digest).decode().rstrip("=")
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
            # Authorization and the complete integrity-checked version have
            # already resolved. A genuine newer source makes this reviewed
            # invocation definitively stale even when its old input is now
            # unavailable. Integrity failures still raise during version proof.
            if type(if_match) is not str or if_match != review["resourceVersion"]:
                raise APRefusal(412, "record_changed", "This RFI record changed. Review it again.", "If-Match")
            if refusal:
                raise refusal
            fingerprint = body.get("fingerprint")
            if type(fingerprint) is not str or not fingerprint.isascii() or not hmac.compare_digest(fingerprint, review["fingerprint"]):
                raise APRefusal(412, "preflight_changed", "The reviewed RFI facts or current project duty changed. Review this step again.", "fingerprint")
            context["review"] = review
            return context
