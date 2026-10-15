"""Pure authored text and project reference reviews over native source checks.

Review creates no text revision, reference, approval, command or receipt. The
same server-owned native plans and current duties are checked before effects.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import hmac
import json

from .ap_contract import APRefusal
from .library_sessions import LibraryIdentityRefusal
from .library_wire import ACTIONS, ACTION_ROUTES, PROVENANCE, WireRefusal, decode_action_body
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash, material_part
from .core.ids import canonical_json, parse_iso, utcnow

RESOURCE_TYPES = {route.action: route.resource_type for route in ACTION_ROUTES}


class LibraryPreflight:
    def __init__(self, cipher, contract, *, secret):
        if type(secret) is not bytes or len(secret) < 32 or contract.cipher is not cipher:
            raise ValueError("Library review requires one owned scoped runtime and private server key")
        self.cipher, self.contract, self.secret = cipher, contract, secret
        self.domain = cipher.plugin("library")

    @staticmethod
    def _body(action, body, *, effect=False):
        if type(body) is not dict:
            raise APRefusal(422, "invalid_body", "Use one exact library object.", "body")
        try:
            decoded = decode_action_body(action, json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(), effect=effect)
            return {key: value for key, value in decoded.items() if key != "fingerprint"}
        except WireRefusal as exc:
            raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
        except (TypeError, ValueError, RecursionError):
            raise APRefusal(422, "invalid_body", "Use the fixed exact values for this library action.", "body") from None

    @staticmethod
    def _effects():
        return {"entriesDelta": 0, "revisionsDelta": 0, "headsDelta": 0, "documentsDelta": 0,
                "documentRevisionsDelta": 0, "referencePlansDelta": 0, "approvalsDelta": 0,
                "projectReferencesDelta": 0, "approvalStatus": None, "journalDelta": 0,
                "mailSinkDelta": 0, "externalDistribution": False, "contractExecution": False,
                "engineeringCertification": False, "projectReferenceOnly": True}

    @staticmethod
    def _check(code, message, target):
        return {"code": code, "status": "passed", "message": message, "target": target, "fix": None}

    @staticmethod
    def _refusal(exc, target):
        if isinstance(exc, APRefusal):
            return exc
        if isinstance(exc, LibraryIdentityRefusal):
            return APRefusal(exc.status, exc.code, exc.message, exc.target)
        if isinstance(exc, ApprovalExpired):
            return APRefusal(423, "library_authorization_expired", "This library authorization expired. Request fresh review.", "approval")
        if isinstance(exc, StaleApprovalError):
            return APRefusal(412, "library_source_changed", "The original authored text, reference purpose or current PM duty changed. Review again.", target)
        if isinstance(exc, PermissionError):
            return APRefusal(403, "actual_library_pm_required", "This step requires the person's own current project duty.", "duty")
        if isinstance(exc, ApprovalError):
            return APRefusal(409, "library_action_unavailable", "The current owned source or original authorization does not permit this step.", target)
        return APRefusal(423, "library_source_unavailable", "This library source cannot currently be verified.", target)

    def _service(self, name, *args, **kwargs):
        check = getattr(self.cipher, name, None)
        if not callable(check):
            raise ApprovalError("The required pure native library check is unavailable")
        return check(*args, **kwargs)


    def _duplicates(self, context, plan_id, operation, manifest):
        for proof in self.domain.approval_inventory(project_ids=(context["projectId"],)):
            approval = proof["approval"]
            if (approval["subject_id"] == plan_id and approval["operation"] == operation
                    and approval["status"] in ("pending", "granted") and parse_iso(approval["expires_at"]) > utcnow()
                    and approval["material_hash"] == material_hash(manifest)
                    and canonical_json(approval["manifest"].get("governance")) == canonical_json(manifest.get("governance"))):
                raise APRefusal(409, "duplicate_request", "This project reference already has this current review request.", "approval")

    @staticmethod
    def _preview(plan, source=None, reference=None):
        if source is None:
            original = plan.get("original")
            entry = original["entry"]["record"] if original else None
            revision = original["currentRevision"]["record"] if original else None
            return {"kind": plan.get("kind", entry["kind"] if entry else None),
                    "title": plan.get("title", entry["title"] if entry else None),
                    **{key: plan[key] for key in ("text", "encoding", "byteCount", "sourceLocator")},
                    "entryId": entry["id"] if entry else None, "revisionId": None,
                    "revisionNumber": revision["revision"] + 1 if revision else 1,
                    "previousRevisionId": revision["id"] if revision else None,
                    "sourceKind": plan.get("sourceKind", "practice-authored-editor-text/1"),
                    "targetLocator": None, "purpose": None}
        entry, revision = source["entry"]["record"], source["revision"]["record"]
        intent = reference["record"] if reference else plan
        return {"kind": entry["kind"], "title": entry["title"],
                **{key: revision[key] for key in ("text", "encoding", "byteCount", "sourceLocator", "sourceKind")},
                "entryId": entry["id"], "revisionId": revision["id"], "revisionNumber": revision["revision"],
                "previousRevisionId": revision["previousRevisionId"],
                "targetLocator": intent["targetLocator"], "purpose": intent["purpose"]}

    def _prospect(self, context, action, resource_id, typed):
        actor = context["login"]
        effects, manifest, approval_clock = self._effects(), None, None
        if action == "library.create":
            plan = self.domain.create_preflight(resource_id, typed, actor=actor)
            source_facts = {"project": self.cipher.project(context["projectId"]), "sourceKind": plan["sourceKind"]}
            preview = self._preview(plan)
            effects.update(entriesDelta=1, revisionsDelta=1, headsDelta=1, documentsDelta=1, documentRevisionsDelta=1)
            message = "Store one exact authored text revision with its source locator. No contract is executed or issued."
        elif action == "library.revise":
            plan = self.domain.revise_preflight(resource_id, typed, actor=actor)
            source_facts = {"original": plan["original"]}
            preview = self._preview(plan)
            effects.update(revisionsDelta=1, headsDelta=1, documentRevisionsDelta=1)
            message = "Append the exact successor text and retain its predecessor. Existing original project references remain historical."
        elif action == "library.prepareReference":
            plan = self.domain.reference_preflight(resource_id, typed, actor=actor)
            source_facts = {"source": plan["source"]}
            preview = self._preview(plan, source=plan["source"])
            effects.update(referencePlansDelta=1)
            message = "Prepare an immutable reference plan for this exact current text and declared project purpose. It does not adopt the reference."
        else:
            if action == "library.requestAdoption":
                checked = self._service("check_library_reference_request", resource_id, requested_by=actor, actor_role="pm")
                manifest = checked["manifest"]
                self._duplicates(context, resource_id, "library.adopt_reference", manifest)
                effects.update(approvalsDelta=1, approvalStatus="pending")
                message = "Request a different actual project PM to review the exact internal reference and purpose."
            elif action == "library.approveAdoption":
                checked = self._service("check_library_reference_grant", resource_id, approver=actor, approver_role="pm")
                manifest = checked["manifest"]
                effects.update(approvalStatus="granted")
                message = "Authorize the unchanged internal reference. The reference is created only when the same grant is applied."
            else:
                checked = self._service("check_library_reference_execution", resource_id, actor=actor)
                manifest = checked["manifest"]
                effects.update(approvalStatus="consumed", projectReferencesDelta=1)
                message = "Create one immutable project reference containing this exact text under the original independent PM grant. No signature, issue or financial effect occurs."
            plan = {key: value for key, value in checked.items() if key not in ("manifest", "governors")}
            reference = checked["plan"] if "record" in checked["plan"] else checked["plan"]["plan"]
            source = checked.get("source") or checked["plan"]["source"]
            source_facts = {"source": source, "referencePlan": reference}
            if "approval" in checked:
                approval = checked["approval"]
                source_facts["originalApproval"] = self.domain.approval_proof(approval["id"])
                approval_clock = {"expiresAt": approval["expires_at"], "originalExpiresAt": approval["manifest"]["expires_at"]}
            preview = self._preview(plan, source=source, reference=reference)
        return {"plan": plan, "sourceFacts": source_facts, "manifest": manifest, "preview": preview,
                "safeEffects": effects, "approvalClock": approval_clock,
                "checks": [self._check("owned_authored_reference_ready", message, RESOURCE_TYPES[action])], "changes": []}

    def _evaluate(self, person_id, action, resource_id, typed):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported library action.", "action")
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
                raise ApprovalError("This first library entry requires disposable memory")
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
            fingerprint = "libpf1." + base64.urlsafe_b64encode(digest).decode().rstrip("=")
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
                raise APRefusal(412, "record_changed", "This library record changed. Review it again.", "If-Match")
            fingerprint = body.get("fingerprint")
            if type(fingerprint) is not str or not fingerprint.isascii() or not hmac.compare_digest(fingerprint, review["fingerprint"]):
                raise APRefusal(412, "preflight_changed", "The reviewed authored text or current PM duty changed. Review this step again.", "fingerprint")
            context["review"] = review
            return context
