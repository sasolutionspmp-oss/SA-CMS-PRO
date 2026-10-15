"""Scratch protocol: fixed commercial reviews with no effects or AP inheritance.

The scoped presenter supplies current actual duty and private resource versions;
fixed branches reuse shared source/domain plans. This module never imports a
generic effect runner or writes reservations.
"""
from __future__ import annotations

import base64
import hmac
import json
from hashlib import sha256

from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash, material_part
from apps.cipher.core.ids import canonical_json, parse_iso, utcnow
from apps.cipher.core.money import money
from apps.cipher.domain.people import IdentityRefused
from .commercial_wire import (ACTIONS, ACTION_ROUTES, PROVENANCE, WireRefusal, decode_action_body,
                             scoped_previous_lines, scoped_revision_row)


RESOURCE_TYPES = {route.action: route.resource_type for route in ACTION_ROUTES}


class CommercialPreflight:
    def __init__(self, cipher, contract, *, secret):
        if type(secret) is not bytes or len(secret) < 32 or contract.cipher is not cipher:
            raise ValueError("Commercial review requires its owned scoped contract and private server key")
        self.cipher, self.contract, self.secret = cipher, contract, secret
        self.domain = cipher.plugin("commercial")

    @staticmethod
    def _check(code, message, target, *, status="passed", fix=None):
        return {"code": code, "status": status, "message": message, "target": target, "fix": fix}

    @staticmethod
    def _money(value):
        cents = int(money(value) * 100)
        if abs(cents) > 999_999_999_999_999:
            raise APRefusal(422, "invalid_estimate", "The proposed exact amount exceeds the estimate range.", "amount")
        return cents

    def _service(self, name, *args, **kwargs):
        check = getattr(self.cipher, name, None)
        if not callable(check):
            raise ApprovalError("The fixed shared commercial check is unavailable")
        return check(*args, **kwargs)

    def _approvals(self, project_id, estimate_id):
        return self.cipher.estimates.estimate_approval_inventory((project_id,), (estimate_id,))

    def _duplicates(self, context, estimate_id, manifest):
        for approval in self._approvals(context["projectId"], estimate_id):
            if approval["status"] not in ("pending", "granted") or parse_iso(approval["expires_at"]) <= utcnow():
                continue
            if (approval["material_hash"] == material_hash(manifest)
                    and approval["manifest"].get("governance") == manifest.get("governance")):
                raise APRefusal(409, "duplicate_request", "This revision already has a current acceptance request.", "estimate")

    def _preview(self, plan):
        calculated = plan["estimatePlan"]
        return {"lines": [{"lineNo": engine["line_no"], "description": engine["description"],
                           "quantity": engine["quantity"], "unit": engine["unit"],
                           "unitPriceCents": self._money(engine["unit_price"]), "amountCents": self._money(engine["amount"]),
                           "sourceLocator": fact["source_locator"], "costCode": fact["cost_code"],
                           **({"previousLineId": fact["previous_line_id"]} if plan["previousId"] else {})}
                          for engine, fact in zip(calculated["lines"], plan["manualFacts"])],
                "subtotalCents": self._money(calculated["subtotal"]), "contingencyCents": self._money(calculated["contingency"]),
                "totalCents": self._money(calculated["total"]), "revision": calculated["revision"]}

    def _prospect(self, context, action, resource_id, typed):
        effects, changes, checks = self._effects(), [], []
        manifest, preview, approval_clock = None, None, None
        actor = context["login"]
        if action in ("estimate.create", "estimate.revise"):
            scoped_revision_row(self.cipher, context["authority"], typed["documentRevisionId"], project_id=context["projectId"])
            if action == "estimate.revise":
                scoped_previous_lines(self.cipher, context["authority"], resource_id, typed["lines"])
                plan = self.domain.revise_preflight(resource_id, typed, actor=actor)
                previous = self.domain.source(resource_id)
                opened = [approval["id"] for approval in self._approvals(context["projectId"], resource_id)
                          if approval["status"] in ("pending", "granted")]
                if opened:
                    changes.append({"code": "open_acceptances_invalidated", "message": "Revising this estimate closes its existing open acceptance requests.",
                                    "target": "approval", "affectedRecordIds": opened})
                changes.append({"code": "estimate_superseded", "message": "The current revision remains in history and this action creates its next draft revision.",
                                "target": "estimate", "affectedRecordIds": [resource_id]})
            else:
                plan = self.domain.create_preflight(resource_id, typed, actor=actor)
                previous = None
            preview = self._preview(plan)
            source_facts = {"drawing": plan["estimatePlan"]["source_proof"], "previous": previous,
                            "manualFacts": plan["manualFacts"], "overlaps": plan["estimatePlan"]["overlaps"]}
            effects.update(createsEstimateRevision=True, estimateStatus="draft")
            checks.append(self._check("exact_estimate_ready", "The current owned drawing and exact entered values produce this draft revision.", "estimate"))
            checks.append(self._check("manual_quantity_source", "The quantities and drawing locators were entered manually. Geometry is unverified.", "lines", status="warning",
                                      fix="Review the manual quantities against the owned drawing."))
        elif action == "estimate.request":
            checked = self._service("check_estimate_request", resource_id, requested_by=actor, actor_role="estimator")
            manifest, plan = checked["manifest"], checked["plan"]
            source_facts = {"engine": checked["source"], "commercial": self.domain.source(resource_id)}
            self._duplicates(context, resource_id, manifest)
            effects.update(approvalStatus="pending", estimateStatus="draft")
            checks.append(self._check("acceptance_request_ready", "This exact current revision may be requested for independent estimator review.", "estimate"))
        elif action in ("estimate.accept", "estimate.apply"):
            approval = self.cipher.approvals.get(resource_id)
            if action == "estimate.accept":
                checked = self._service("check_estimate_grant", resource_id, approver=actor, approver_role="estimator")
                effects.update(approvalStatus="granted", estimateStatus="draft")
                message = "A different current estimator may authorize acceptance. Applying the grant records the accepted baseline."
            else:
                checked = self._service("check_estimate_application", resource_id, actor=actor)
                effects.update(approvalStatus="consumed", estimateStatus="approved", createsAcceptedBaseline=True)
                message = "This current estimator may apply the intact independent grant and record the accepted baseline."
                others = [identifier for identifier in checked["plan"]["invalidated_approval_ids"] if identifier != resource_id]
                if others:
                    changes.append({"code": "other_acceptances_invalidated", "message": "Applying this grant closes other open acceptance requests for this revision.",
                                    "target": "approval", "affectedRecordIds": others})
            manifest, plan = checked["manifest"], checked["plan"]
            source_facts = {"engine": checked["source"], "commercial": self.domain.source(approval["subject_id"]),
                            "approval": approval, "originalApproval": checked["original_approval_source"]}
            approval_clock = {"expiresAt": approval["expires_at"], "originalExpiresAt": approval["manifest"]["expires_at"]}
            checks.append(self._check("acceptance_authorization_ready", message, "approval"))
        elif action == "estimate.prepareHandoff":
            package = self.domain.current_package(context["projectId"], actor=actor)
            plan = self.domain.handoff_preflight(resource_id, package["id"], actor=actor)
            source_facts = {"source": plan["source"], "package": plan["package"]}
            effects.update(createsHandoff=True, estimateStatus="approved")
            checks.append(self._check("accepted_handoff_ready", "The original accepted lines and audited package terms produce one source-preserving handoff.", "estimate"))
        else:
            plan = self.domain.commitment_preflight(resource_id, actor=actor)
            source_facts = {"handoff": plan["handoff"], "sov": plan["sov_lines"]}
            effects.update(createsCommitment=True, estimateStatus="approved")
            checks.append(self._check("draft_commitment_ready", "The reviewed handoff creates one subcontract draft with the exact mapped SOV. Contract review and execution remain separate.", "handoff"))
        return {"plan": plan, "sourceFacts": source_facts, "manifest": manifest, "preview": preview,
                "safeEffects": effects, "checks": checks, "changes": changes, "approvalClock": approval_clock}

    @staticmethod
    def _body(action, body, *, effect=False):
        try:
            raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            decoded = decode_action_body(action, raw, effect=effect)
            return {key: value for key, value in decoded.items() if key != "fingerprint"}
        except WireRefusal as exc:
            raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
        except (TypeError, ValueError, RecursionError):
            raise APRefusal(422, "invalid_body", "Use the fixed exact values for this commercial action.", "body") from None

    @staticmethod
    def _effects():
        return {"createsEstimateRevision": False, "approvalStatus": None, "estimateStatus": None,
                "createsAcceptedBaseline": False, "createsHandoff": False, "createsCommitment": False,
                "workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0, "journalPreview": [],
                "externalAccounting": "unavailable", "payment": "not_started", "providerCallBound": 0,
                "customerIssue": "not_started", "customerAward": "not_started", "budgetAdoption": "not_started"}

    @staticmethod
    def _refusal(exc, target):
        if isinstance(exc, APRefusal):
            return exc
        if isinstance(exc, WireRefusal):
            return APRefusal(exc.status, exc.code, exc.message, exc.target)
        if isinstance(exc, ApprovalExpired):
            return APRefusal(423, "acceptance_expired", "The estimator authorization expired. Request fresh review.", "approval")
        if isinstance(exc, StaleApprovalError):
            return APRefusal(412, "commercial_source_changed", "The accepted scope, source or current duty changed. Review again.", target)
        if isinstance(exc, IdentityRefused):
            return APRefusal(403, "actual_commercial_duty_required", "Current actual project commercial duty does not permit this step.", "duty")
        if isinstance(exc, ApprovalError):
            return APRefusal(409, "acceptance_unavailable", "This estimator acceptance authorization is unavailable for the step.", "approval")
        return APRefusal(423, "commercial_source_unavailable", "This action's current source records cannot be verified.", target)

    def _evaluate(self, person_id, action, resource_id, typed):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported commercial action.", "action")
        # authorize performs only minimal scoped references and current actual
        # duty checks before private estimates/history/approval/handoff facts.
        context = self.contract.authorize(person_id, action, resource_id)
        version = self.contract.version(person_id, resource_id, RESOURCE_TYPES[action])
        context["typed"] = typed
        effects, checks, changes, refusal, prospect = self._effects(), [], [], None, None
        try:
            self.cipher.db.require_practice_mode()
            self.cipher.db.require_write_authority()
            # This explicit presenter protocol must use only fixed shared domain
            # helpers; arbitrary module/operation/effect selectors are absent.
            prospect = self._prospect(context, action, resource_id, typed)
            effects.update(prospect["safeEffects"])
            checks, changes = prospect["checks"], prospect["changes"]
            context.update(plan=prospect["plan"], sourceFacts=prospect["sourceFacts"], manifest=prospect.get("manifest"))
        except Exception as exc:
            if isinstance(exc, (APRefusal, WireRefusal)) and exc.status == 404:
                raise self._refusal(exc, "record") from None
            refusal = self._refusal(exc, RESOURCE_TYPES[action])
            effects = self._effects()
            checks.append({"code": refusal.code, "status": "blocked", "target": refusal.target,
                           "message": refusal.message, "fix": "Refresh current source, history and actual duty before review."})
        fingerprint = None
        if refusal is None:
            manifest = prospect.get("manifest")
            material = {"provenance": PROVENANCE, "workspace": self.cipher.db.mode_status(),
                        "authority": self.cipher.db.authority_status(), "personId": context["personId"],
                        "login": context["login"], "duty": context["duty"], "scopeHash": context["authority"].scope_hash,
                        "action": action, "resourceId": resource_id, "version": version, "typed": typed,
                        "plan": prospect["plan"], "sourceFacts": prospect["sourceFacts"],
                        "material": material_part(manifest) if manifest else None,
                        "governance": manifest.get("governance") if manifest else None,
                        "approvalClock": prospect.get("approvalClock"), "effects": effects, "preview": prospect.get("preview")}
            digest = hmac.new(self.secret, canonical_json(material).encode(), sha256).digest()
            fingerprint = "cmpf1." + base64.urlsafe_b64encode(digest).decode().rstrip("=")
        review = {**PROVENANCE, "action": action, "resourceId": resource_id, "resourceVersion": version,
                  "version": version, "allowed": refusal is None, "checks": checks, "changes": changes,
                  "safeEffects": effects, "fingerprint": fingerprint}
        if refusal is None and prospect.get("preview") is not None:
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
                raise APRefusal(412, "record_changed", "This commercial record changed. Review it again.", "If-Match")
            fingerprint = body.get("fingerprint")
            if type(fingerprint) is not str or not fingerprint.isascii() or not hmac.compare_digest(fingerprint, review["fingerprint"]):
                raise APRefusal(412, "preflight_changed", "The reviewed commercial facts changed. Review this step again.", "fingerprint")
            context["review"] = review
            return context
