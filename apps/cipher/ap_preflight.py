"""Pure, scoped AP checks and keyed fingerprints for the practice action slice.

Review never runs an effect and rolls it back. The consequential service methods
share these source checks; only their effect paths grant or consume authority.
"""
from __future__ import annotations

import base64
import hmac
from hashlib import sha256
from functools import wraps
from typing import Any

from .ap_contract import APContract, APRefusal
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash, material_part
from .core.db import WorkspaceModeError
from .core.ids import canonical_json, parse_iso, utcnow
from .core.money import MoneyError, money
from .domain.bills import BillError
from .domain.contracts import ContractError, CoverageError
from .domain.ledger import LedgerError, PeriodNotOpen
from .domain.people import IdentityIntegrityError, IdentityRefused, PeopleError


ACTIONS = ("bill.requestApproval", "bill.approve", "bill.post")
MAX_SAFE_CENTS = (1 << 53) - 1


def _locked(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.c.db._lock:
            return method(self, *args, **kwargs)
    return run


def _cents(value: Any) -> int:
    try:
        result = int(money(value) * 100)
    except (MoneyError, TypeError, ValueError) as exc:
        raise APRefusal(423, "invalid_record", "A stored amount cannot be reviewed as exact cents.", "money") from exc
    if abs(result) > MAX_SAFE_CENTS:
        raise APRefusal(423, "amount_out_of_range", "A stored amount exceeds the client's exact integer range.", "money")
    return result


class APPreflight:
    def __init__(self, cipher, contract: APContract | None = None, *, secret: bytes):
        if type(secret) is not bytes or len(secret) < 16:
            raise ValueError("AP review requires a private fingerprint key of at least 16 bytes.")
        self.c = cipher
        self.contract = contract if contract is not None else APContract(cipher, secret=secret)
        self.secret = secret
        self.now = utcnow

    def authorize(self, person_id: str, action: str, resource_id: str) -> dict[str, Any]:
        """Resolve current human duty and scope without rejecting completed lifecycle.

        Receipt replay uses this check before it discloses an original result.
        """
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "This practice action is not supported.", "action")
        return self.contract.require_resource(person_id, action, resource_id)

    @staticmethod
    def _body(action: str, body: dict[str, Any] | None, *, action_body: bool = False) -> dict[str, Any]:
        if body is None:
            body = {}
        if type(body) is not dict:
            raise APRefusal(422, "invalid_body", "Send the named JSON fields for this action.", "body")
        allowed = {"periodId", "reason"} if action == "bill.post" else set()
        if action_body:
            allowed.add("fingerprint")
        if any(type(key) is not str or key not in allowed for key in body):
            raise APRefusal(422, "invalid_body", "This action contains an unsupported field.", "body")
        if action != "bill.post":
            return {}
        period, reason = body.get("periodId"), body.get("reason", "")
        if type(period) is not str or not period.strip() or len(period) > 200 or period != period.strip():
            raise APRefusal(422, "invalid_period", "Choose an accounting period for the review.", "periodId")
        if type(reason) is not str or len(reason) > 500:
            raise APRefusal(422, "invalid_reason", "Use a posting reason of at most 500 characters.", "reason")
        return {"periodId": period, "reason": reason.strip()}

    @_locked
    def review(self, person_id: str, action: str, resource_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        typed = self._body(action, body)
        _context, review, _refusal = self._evaluate(person_id, action, resource_id, typed)
        return review

    @_locked
    def verify(self, person_id: str, action: str, resource_id: str, body: dict[str, Any], if_match: str,
               fingerprint: str | None = None) -> dict[str, Any]:
        """Recheck a new action under the caller's write lock immediately before apply."""
        typed = self._body(action, body, action_body=True)
        fingerprint = body.get("fingerprint") if fingerprint is None else fingerprint
        context, review, refusal = self._evaluate(person_id, action, resource_id, typed)
        # Integrity and clock-bound failures take precedence over a harmless version
        # mismatch. No bookkeeping is written by this review refusal.
        if refusal is not None:
            raise refusal
        if type(if_match) is not str or if_match != review["resourceVersion"]:
            raise APRefusal(412, "record_changed", "This record changed. Refresh it and review again.", "If-Match")
        if (type(fingerprint) is not str or len(fingerprint) > 512
                or not hmac.compare_digest(fingerprint, review["fingerprint"])):
            raise APRefusal(412, "preflight_changed", "The reviewed facts changed. Review this action again.", "fingerprint")
        context["review"] = review
        return context

    @staticmethod
    def _check(code: str, status: str, target: str, message: str, fix: str | None = None) -> dict[str, Any]:
        return {"code": code, "status": status, "target": target, "message": message, "fix": fix}

    def _effects(self, bill: dict[str, Any], action: str, plan: list[dict[str, Any]]) -> dict[str, Any]:
        preview = []
        for journal in plan:
            lines = []
            for line in journal["lines"]:
                account = self.c.db.one("SELECT name FROM accounts WHERE code=?", (line["account"],))
                lines.append({"account": line["account"], "accountName": account["name"] if account else None,
                              "projectId": line.get("project_id"), "partyId": line.get("party_id"), "memo": line.get("memo", ""),
                              "debitCents": _cents(line.get("debit", "0")), "creditCents": _cents(line.get("credit", "0"))})
            preview.append({"periodId": journal["period_id"], "description": journal["description"],
                            "sourceVersion": journal["source_version"], "lines": lines})
        return {"billStatus": "posted" if action == "bill.post" else "approved" if action == "bill.approve" else bill["status"],
                "workingLedgerJournalDelta": len(plan), "apPayableDeltaCents": _cents(bill["amount_due"]) if action == "bill.post" else 0,
                "amountDueCents": _cents(bill["amount_due"]), "retainageCents": _cents(bill["retainage_this_period"]),
                "journalPreview": preview, "externalAccounting": "unavailable", "payment": "not_started"}

    def _authority_facts(self, context: dict[str, Any]) -> dict[str, Any]:
        person_id, project_id = context["personId"], context["projectId"]
        return {"person": self.c.db.one("SELECT * FROM people_persons WHERE id=?", (person_id,)),
                "membership": self.c.db.query("SELECT * FROM people_memberships WHERE person_id=? AND project_id=? ORDER BY id", (person_id, project_id)),
                "grants": self.c.db.query("SELECT * FROM people_grants WHERE person_id=? ORDER BY seq", (person_id,)),
                "duty": context["duty"], "projectId": project_id}

    @staticmethod
    def _safe_refusal(exc: Exception, target: str) -> APRefusal:
        if isinstance(exc, APRefusal):
            return exc
        if isinstance(exc, ApprovalExpired):
            return APRefusal(423, "approval_expired", "The business authorization expired. Request fresh approval.", target)
        if isinstance(exc, StaleApprovalError):
            return APRefusal(412, "approval_stale", "The business facts or authority changed. Request fresh approval.", target)
        if isinstance(exc, PeriodNotOpen):
            return APRefusal(423, "period_locked", "The selected accounting period is closed or locked.", "periodId")
        if isinstance(exc, CoverageError):
            return APRefusal(423, "coverage_required", "Current required supplier coverage is unavailable. Review the coverage records.", target)
        if isinstance(exc, (IdentityIntegrityError, WorkspaceModeError)):
            return APRefusal(423, "integrity_unavailable", "The practice workspace controls cannot be verified.", "workspace")
        if isinstance(exc, (IdentityRefused, PermissionError)):
            return APRefusal(403, "duty_refused", "This person cannot perform this bill action with their current authority.", target)
        if isinstance(exc, ApprovalError):
            return APRefusal(409, "approval_unavailable", "This authorization is no longer available for the action.", target)
        if isinstance(exc, (BillError, LedgerError, ContractError, PeopleError)):
            return APRefusal(423, "bill_not_ready", "The bill's current source or control records do not permit this action. Refresh and review them.", target)
        return APRefusal(500, "review_unavailable", "The current bill review could not be verified.", target)

    def _deadline(self, approval: dict[str, Any]) -> None:
        try:
            expiry = parse_iso(approval["expires_at"])
            if expiry.utcoffset() is None:
                raise ValueError("missing time zone")
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            raise APRefusal(423, "invalid_authorization", "The authorization deadline cannot be verified.", "approval") from exc
        if expiry <= self.now():
            raise ApprovalExpired("The business authorization expired.")

    def _duplicate_request(self, bill: dict[str, Any], manifest: dict[str, Any]) -> None:
        for approval in self.c.approvals.list():
            if (approval["operation"] != "bill.approve" or approval["subject_id"] != bill["id"]
                    or approval["status"] not in ("pending", "granted")):
                continue
            self.c.bills._audited_authorization(approval["id"], bill["id"], status=approval["status"])
            try:
                self._deadline(approval)
            except ApprovalExpired:
                continue
            if (material_hash(manifest) == approval["material_hash"]
                    and manifest.get("governance") == approval["manifest"].get("governance")):
                raise APRefusal(409, "duplicate_request", "This bill already has a current business approval request.", approval["id"])

    def _evaluate(self, person_id: str, action: str, resource_id: str, typed: dict[str, Any]):
        context = self.authorize(person_id, action, resource_id)
        version = self.contract.version(person_id, resource_id, approval=action == "bill.approve")
        approval = context["record"] if action == "bill.approve" else None
        bill = self.c.bills.get(approval["subject_id"]) if approval else context["record"]
        context["bill"] = bill
        checks = [self._check("person_authorized", "passed", "person", "The registered person holds this duty in the project's current scope.")]
        changes: list[dict[str, Any]] = []
        plan: list[dict[str, Any]] = []
        refusal = None
        manifest = None
        try:
            self.c.db.require_practice_mode()
            if action == "bill.requestApproval":
                manifest = self.c.check_request_approval("bill.approve", bill["id"], actor_role=context["duty"], requested_by=context["login"])
                self._duplicate_request(bill, manifest)
                checks.append(self._check("request_ready", "passed", "bill", "Current source facts are eligible for a new business approval request."))
            elif action == "bill.approve":
                if approval["status"] != "pending":
                    raise APRefusal(409, "approval_unavailable", "This business authorization is no longer pending.", "approval")
                self._deadline(approval)
                checked = self.c.check_approval_grant(approval["id"], approver=context["login"], approver_role=context["duty"])
                manifest = self.c._manifest("bill.approve", bill["id"], "pm")
                context["approval"] = checked["approval"]
                checks.append(self._check("business_approval_ready", "passed", "approval", "The pending request and current business facts agree. Approval creates no journal or payable."))
            else:
                approval_id = bill.get("business_approval_id")
                if not approval_id:
                    raise APRefusal(423, "business_approval_required", "This bill needs a recorded business approval before posting.", "bill")
                approval = self.c.approvals.get(approval_id)
                self._deadline(approval)
                if typed["periodId"] != bill["period_id"] and not typed["reason"]:
                    raise APRefusal(422, "posting_reason_required", "Posting in another period requires a reason.", "reason")
                checked = self.c.check_bill_posting(bill["id"], actor=context["login"], actor_role=context["duty"],
                                                   period_id=typed["periodId"], reason=typed["reason"])
                context.update(checked)
                manifest, plan = checked["manifest"], checked["plan"]
                checks.append(self._check("posting_ready", "passed", "bill", "An independent accountant can post the intact business grant in this open period."))
                checks.append(self._check("journal_plan_verified", "passed", "journal", "The entries shown are the exact current working-ledger posting plan."))
            effects = self._effects(bill, action, plan)
        except Exception as exc:
            refusal = self._safe_refusal(exc, "approval" if action == "bill.approve" else "bill")
            checks.append(self._check(refusal.code, "blocked", refusal.target or "bill", refusal.message,
                                      "Refresh the record and review again."))
            # Blocked reviews never describe a proposed economic effect as available.
            effects = {"billStatus": bill.get("status"), "workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0,
                       "journalPreview": [], "externalAccounting": "unavailable", "payment": "not_started"}
        if approval is not None:
            bound = approval["manifest"].get("amounts") or {}
            for field, current in (("amountDueCents", bill.get("amount_due")), ("retainageCents", bill.get("retainage_this_period"))):
                before = bound.get("amount_due" if field == "amountDueCents" else "retainage_this_period")
                if before is not None and current is not None and _cents(before) != _cents(current):
                    changes.append({"field": field, "before": _cents(before), "after": _cents(current)})
        fingerprint = None
        if refusal is None:
            facts = {"workspace": self.c.db.mode_status(), "person": self._authority_facts(context), "action": action,
                     "resourceId": resource_id, "version": version, "body": typed, "material": material_part(manifest),
                     "governance": manifest.get("governance"), "bill": bill,
                     "approval": approval, "period": context.get("period"), "plan": plan}
            digest = hmac.new(self.secret, canonical_json(facts).encode("utf-8"), sha256).digest()
            fingerprint = "pf1." + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        context["manifest"] = manifest
        if approval is not None:
            context["approval"] = approval
        review = {"action": action, "resourceId": resource_id, "resourceVersion": version, "version": version,
                  "allowed": refusal is None, "checks": checks, "changes": changes, "safeEffects": effects, "fingerprint": fingerprint}
        return context, review, refusal
