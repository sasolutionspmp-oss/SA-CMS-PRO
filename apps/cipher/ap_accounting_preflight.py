"""zero-write review of fixed synthetic accounting actions.

Worker review never claims a lease or invokes a simulator. An actual worker act
requires the separate durable invocation runner, outside the AP SQL wrapper.
"""
from __future__ import annotations

import base64
import hmac
from hashlib import sha256

from .ap_contract import APRefusal, PROVENANCE
from .ap_intake_preflight import APIntakePreflight
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash, material_part
from .core.db import WorkspaceModeError
from .core.ids import canonical_json, parse_iso, utcnow
from .domain.people import IdentityIntegrityError, IdentityRefused
from .ap_accounting_contract import ACTIONS, RESOURCE_TYPES, OPERATION, approval_proof
from .domain.accounting import AccountingError


class APAccountingPreflight(APIntakePreflight):
    def __init__(self, cipher, contract, *, secret, worker=None):
        if type(secret) is not bytes or len(secret) < 32 or contract.cipher is not cipher:
            raise ValueError("Accounting review requires the owned contract and private server key.")
        self.c, self.contract, self.secret = cipher, contract, secret
        self.accounting, self.worker, self.now = cipher.plugin("accounting"), worker, utcnow

    def authorize(self, person_id, action, resource_id):
        return self.contract.authorize(person_id, action, resource_id)

    @classmethod
    def _body(cls, action, body=None, *, action_body=False):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported synthetic accounting action.", "action")
        body = {} if body is None else body
        allowed = {"fingerprint"} if action_body else set()
        if type(body) is not dict or set(body) - allowed:
            raise APRefusal(422, "invalid_body", "This fixed action accepts no accounting or actor selectors.", "body")
        return {}

    @staticmethod
    def _safe_refusal(exc, target):
        if isinstance(exc, APRefusal):
            return exc
        if isinstance(exc, ApprovalExpired):
            return APRefusal(423, "approval_expired", "The handoff authorization expired. Request fresh approval.", "approval")
        if isinstance(exc, StaleApprovalError):
            return APRefusal(412, "approval_stale", "The original accounting source, mapping or authority changed. Review and request fresh approval.", "approval")
        if isinstance(exc, (IdentityRefused, PermissionError)):
            return APRefusal(403, "accountant_refused", "Current registered accountant authority does not permit this step.", "duty")
        if isinstance(exc, (WorkspaceModeError, IdentityIntegrityError)):
            return APRefusal(423, "workspace_unavailable", "The synthetic workspace controls cannot be verified.", "workspace")
        if isinstance(exc, ApprovalError):
            return APRefusal(409, "approval_unavailable", "This accounting handoff authorization is no longer available for this step.", "approval")
        if isinstance(exc, AccountingError):
            return APRefusal(423, "accounting_not_ready", "Current audited source facts, mapping, delivery state or duties do not permit this step.", target)
        return APRefusal(500, "review_unavailable", "The current synthetic accounting review could not be verified.", target)

    def _deadline(self, approval):
        try:
            deadline = parse_iso(approval["expires_at"])
            if deadline.utcoffset() is None:
                raise ValueError("missing time zone")
        except (KeyError, TypeError, ValueError, OverflowError):
            raise APRefusal(423, "invalid_authorization", "The accounting authorization deadline cannot be verified.", "approval") from None
        if deadline <= self.now():
            raise ApprovalExpired("The accounting handoff authorization expired.")

    def _duplicate_request(self, plan, manifest):
        for approval in self.accounting.approval_inventory(project_ids=(plan["project_id"],)):
            if approval["subject_id"] != plan["id"] or approval["status"] not in ("pending", "granted"):
                continue
            try:
                self._deadline(approval)
            except ApprovalExpired:
                continue
            if (material_hash(manifest) == approval["material_hash"]
                    and manifest.get("governance") == approval["manifest"].get("governance")):
                raise APRefusal(409, "duplicate_request", "This plan already has a current accounting handoff request.", "plan")

    def _qualified_worker(self):
        # Fixed initialized server capability validation does not retrieve or
        # call an adapter. A body cannot introduce a worker/provider/selector.
        try:
            from .accounting_worker import require_bound_worker
            require_bound_worker(self.worker, domain=self.accounting)
        except Exception:
            raise APRefusal(423, "worker_unavailable", "The fixed disposable synthetic accounting worker is unavailable.", "worker") from None
        if not self.c.db.in_memory:
            raise APRefusal(423, "worker_unavailable", "This simulation currently requires a disposable memory practice workspace.", "workspace")

    @staticmethod
    def _effects():
        return {"workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0, "journalPreview": [],
                "nativePaymentProviderCalls": 0, "preflightAccountingSimulatorCalls": 0, "accountingSimulatorCallBound": 0,
                "quickBooksAccepted": False, "externalAccounting": "unavailable", "payment": "not_started",
                "createsPlan": False, "createsApproval": False, "grantsApproval": False, "createsIntent": False,
                "startsSeparateWorkerInvocation": False, "intendedWorkerPhase": None, "approvalStatus": None,
                "intentStatus": None}

    def _evaluate(self, person_id, action, resource_id, typed):
        context = self.authorize(person_id, action, resource_id)
        version = self.contract.version(person_id, resource_id, RESOURCE_TYPES[action])
        record = context["record"]
        context["typed"] = typed
        effects, changes, manifest, plan, refusal = self._effects(), [], None, None, None
        approval = record if RESOURCE_TYPES[action] == "approval" else None
        checks = [self._check("actual_accountant", "passed", "person", "The registered person holds their own current accountant duty in this project.")]
        original_plan = (self.accounting.plan(record["subject_id"]) if approval else
                         self.accounting.plan(record["plan_id"]) if RESOURCE_TYPES[action] == "intent" else
                         record if RESOURCE_TYPES[action] == "plan" else None)
        if original_plan:
            current_bill = self.contract.base._bill(context["authority"], original_plan["bill_id"])
            if current_bill["status"] != "posted":
                changes.append({"field": "sourceBillStatus", "before": "posted", "after": current_bill["status"]})
            try:
                mapping = self.contract.current_mapping(context["authority"], context["projectId"])
                old_version = original_plan["payload"]["mapping"]["version"]
                if old_version != mapping["version"]:
                    changes.append({"field": "mappingVersion", "before": old_version, "after": mapping["version"]})
            except (RuntimeError, ValueError, TypeError, KeyError):
                changes.append({"field": "mappingAvailability", "before": "available", "after": "unavailable"})
        try:
            self.c.db.require_practice_mode()
            self.c.db.require_write_authority()
            if action == "accounting.prepare":
                mapping = self.contract.current_mapping(context["authority"], context["projectId"])
                plan = self.accounting.preparation_preflight(resource_id, mapping["id"], actor=context["login"])
                context["mapping"] = mapping
                effects["createsPlan"] = True
                checks.append(self._check("original_posting_ready", "passed", "bill", "The original installed-work posting and fixed synthetic mapping produce this immutable practice plan."))
            elif action == "accounting.request":
                checked = self.c.check_accounting_queue_request(resource_id, requested_by=context["login"], actor_role="accountant")
                manifest, plan = checked["manifest"], checked["plan"]
                self._duplicate_request(record, manifest)
                effects.update(createsApproval=True, approvalStatus="pending")
                checks.append(self._check("handoff_request_ready", "passed", "plan", "This exact original source and mapping may be requested for independent accountant review."))
            elif action in ("accounting.approve", "accounting.queue"):
                approval_proof(self.c, resource_id)
                self._deadline(approval)
                if action == "accounting.approve":
                    checked = self.c.check_accounting_queue_grant(resource_id, approver=context["login"], approver_role="accountant")
                    effects.update(grantsApproval=True, approvalStatus="granted")
                    message = "A different current accountant may approve this unchanged practice handoff."
                else:
                    checked = self.c.check_accounting_queue_execution(resource_id, actor=context["login"])
                    effects.update(createsIntent=True, approvalStatus="consumed", intentStatus="queued")
                    message = "The intact grant permits one queued intent. Delivery runs as a separate simulation step."
                manifest, plan = checked["manifest"], checked["plan"]
                checks.append(self._check("handoff_authorization_ready", "passed", "approval", message))
            else:
                self._qualified_worker()
                purpose = "lookup" if action == "accounting.lookup" else "reconciliation" if action == "accounting.reconcile" else "delivery"
                plan = self.accounting.worker_preflight(resource_id, actor=context["login"], purpose=purpose)
                phase = plan["provider_purpose"]
                effects.update(startsSeparateWorkerInvocation=True, intendedWorkerPhase=phase,
                               accountingSimulatorCallBound=3 if phase == "lookup" else 1, intentStatus=record["status"])
                context["workerPurpose"] = purpose
                checks.append(self._check("separate_worker_ready", "passed", "intent", "This phase may begin after the original invocation and attempt are committed. The simulation outcome remains to be observed."))
                if phase == "lookup":
                    checks.append(self._check("original_outcome_lookup", "passed", "intent", "Recovery looks up the original logical operation. It cannot submit a replacement in this invocation."))
            context.update(manifest=manifest, plan=plan, approval=approval)
        except Exception as exc:
            if isinstance(exc, APRefusal) and exc.status == 404:
                raise
            refusal = self._safe_refusal(exc, RESOURCE_TYPES[action])
            checks.append(self._check(refusal.code, "blocked", refusal.target, refusal.message, "Refresh and review the current source, duty and delivery state."))
            effects = self._effects()
        fingerprint = None
        if refusal is None:
            private = {"workspace": self.c.db.mode_status(), "authority": self.c.db.authority_status(),
                       "personId": context["personId"], "login": context["login"], "duty": context["duty"],
                       "scope": context["authority"].scope_hash, "accountantProof": context["accountantProof"],
                       "action": action, "resourceId": resource_id, "version": version, "body": typed,
                       "material": material_part(manifest) if manifest else None,
                       "governance": manifest.get("governance") if manifest else None,
                       "approval": approval, "plan": plan, "effects": effects}
            digest = hmac.new(self.secret, canonical_json(private).encode(), sha256).digest()
            fingerprint = "acpf1." + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        review = {**PROVENANCE, "action": action, "resourceId": resource_id, "resourceVersion": version, "version": version,
                  "allowed": refusal is None, "checks": checks, "changes": changes, "safeEffects": effects, "fingerprint": fingerprint}
        return context, review, refusal
