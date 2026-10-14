"""Pure reviews for scoped installed-work preparation and invoice matching.

The browser supplies quantities and source references. Domain preflights compute
the exact proposed content; no review executes an action and rolls it back.
"""
from __future__ import annotations

import base64
import datetime
import hmac
from decimal import Decimal
from hashlib import sha256
from typing import Any

from .ap_contract import APContract, APRefusal
from .ap_intake_contract import ACTIONS, RESOURCE_TYPES, APIntakeContract, MATCH_OPERATION
from .ap_preflight import MAX_SAFE_CENTS, _cents, _locked
from .core.approvals import ApprovalError, ApprovalExpired, StaleApprovalError, material_hash, material_part
from .core.db import WorkspaceModeError
from .core.ids import canonical_json, parse_iso, utcnow
from .core.money import MoneyError, fmt, money
from .domain.ap_intake import APIntakeError, DuplicateInvoiceError
from .domain.bills import BillError
from .domain.contracts import ContractError, CoverageError
from .domain.ledger import LedgerError, PeriodNotOpen
from .domain.people import IdentityIntegrityError, IdentityRefused, PeopleError


def approval_proof(cipher, approval_id: str) -> dict[str, Any]:
    """Verify the entire current lifecycle, returning a stable request receipt."""
    return cipher.plugin("ap_intake").approval_proof(approval_id)


class APIntakePreflight:
    def __init__(self, cipher, contract: APIntakeContract | None = None, *, secret: bytes):
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("Invoice review requires a private server key of at least 32 bytes.")
        self.c, self.secret = cipher, secret
        self.contract = contract or APIntakeContract(cipher, APContract(cipher, secret=secret), secret=secret)
        self.ap = cipher.plugin("ap_intake")
        self.now = utcnow

    def authorize(self, person_id, action, resource_id):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported invoice practice action.", "action")
        return self.contract.authorize(person_id, action, resource_id)

    @staticmethod
    def _text(value, target, *, maximum=200):
        if (type(value) is not str or not value or value != value.strip() or len(value) > maximum
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise APRefusal(422, "invalid_body", "Use a valid value for the named action field.", target)
        return value

    @staticmethod
    def _integer(value, target, *, positive=False):
        if type(value) is not int or value < (1 if positive else 0) or value > MAX_SAFE_CENTS:
            raise APRefusal(422, "invalid_amount", "Use an exact whole-cent amount within the supported range.", target)
        return value

    @classmethod
    def _body(cls, action, body=None, *, action_body=False):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported invoice practice action.", "action")
        if body is None:
            body = {}
        fields = ({"periodId", "installed"} if action == "bill.prepare" else
                  {"invoiceNumber", "invoiceDate", "amountCents", "evidenceRevisionId"} if action == "invoice.receive" else set())
        allowed = fields | ({"fingerprint"} if action_body else set())
        if type(body) is not dict or set(body) - allowed or fields - set(body):
            raise APRefusal(422, "invalid_body", "Send exactly the named JSON fields for this action.", "body")
        if action == "bill.prepare":
            period = cls._text(body["periodId"], "periodId")
            installed = body["installed"]
            if type(installed) is not list or not 1 <= len(installed) <= 100:
                raise APRefusal(422, "invalid_installed", "Provide between one and 100 installed-work lines.", "installed")
            lines, seen = [], set()
            for line in installed:
                if type(line) is not dict or set(line) != {"sovLineId", "cumulativeInstalledCents"}:
                    raise APRefusal(422, "invalid_installed", "Each installed-work line needs its SOV source and cumulative cents.", "installed")
                sid = cls._text(line["sovLineId"], "sovLineId")
                if sid in seen:
                    raise APRefusal(422, "duplicate_line", "List each SOV line once.", "installed")
                seen.add(sid)
                lines.append({"sovLineId": sid, "cumulativeInstalledCents": cls._integer(line["cumulativeInstalledCents"], "cumulativeInstalledCents")})
            # A line ordering change is not a different logical quantity submission.
            return {"periodId": period, "installed": sorted(lines, key=lambda line: line["sovLineId"])}
        if action == "invoice.receive":
            number = cls._text(body["invoiceNumber"], "invoiceNumber", maximum=64)
            date = cls._text(body["invoiceDate"], "invoiceDate", maximum=10)
            try:
                parsed = datetime.date.fromisoformat(date)
                if parsed.isoformat() != date:
                    raise ValueError("noncanonical date")
            except ValueError as exc:
                raise APRefusal(422, "invalid_date", "Use an invoice date in YYYY-MM-DD format.", "invoiceDate") from exc
            return {"invoiceNumber": number, "invoiceDate": date,
                    "amountCents": cls._integer(body["amountCents"], "amountCents", positive=True),
                    "evidenceRevisionId": cls._text(body["evidenceRevisionId"], "evidenceRevisionId")}
        return {}

    @_locked
    def review(self, person_id, action, resource_id, body=None):
        _context, review, _refusal = self._evaluate(person_id, action, resource_id, self._body(action, body))
        return review

    @_locked
    def verify(self, person_id, action, resource_id, body, if_match, fingerprint=None):
        typed = self._body(action, body, action_body=True)
        fingerprint = body.get("fingerprint") if fingerprint is None else fingerprint
        context, review, refusal = self._evaluate(person_id, action, resource_id, typed)
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
    def _check(code, status, target, message, fix=None):
        return {"code": code, "status": status, "target": target, "message": message, "fix": fix}

    @staticmethod
    def _safe_refusal(exc, target):
        if isinstance(exc, APRefusal):
            return exc
        if isinstance(exc, ApprovalExpired):
            return APRefusal(423, "approval_expired", "The match authorization expired. Request fresh approval.", target)
        if isinstance(exc, StaleApprovalError):
            return APRefusal(412, "approval_stale", "The invoice facts or authority changed. Compute the match and request fresh approval.", target)
        if isinstance(exc, DuplicateInvoiceError):
            return APRefusal(409, "duplicate_invoice", "This supplier invoice number is already recorded. Review the existing invoice.", "invoiceNumber")
        if isinstance(exc, MoneyError):
            return APRefusal(422, "invalid_amount", "The proposed amount exceeds the domain's supported exact-money range.", "amountCents")
        if isinstance(exc, PeriodNotOpen):
            return APRefusal(423, "period_locked", "The selected certification period is closed or locked.", "periodId")
        if isinstance(exc, CoverageError):
            return APRefusal(423, "coverage_required", "Required supplier coverage must be reviewed before this action.", target)
        if isinstance(exc, (WorkspaceModeError, IdentityIntegrityError)):
            return APRefusal(423, "integrity_unavailable", "The practice workspace controls cannot be verified.", "workspace")
        if isinstance(exc, (IdentityRefused, PermissionError)):
            return APRefusal(403, "duty_refused", "This person cannot perform this invoice action with their current authority.", "duty")
        if isinstance(exc, ApprovalError):
            return APRefusal(409, "approval_unavailable", "This match authorization is no longer available for the action.", "approval")
        if isinstance(exc, (APIntakeError, BillError, LedgerError, ContractError, PeopleError)):
            return APRefusal(423, "intake_not_ready", "The current source or control records do not permit this action. Refresh and review them.", target)
        return APRefusal(500, "review_unavailable", "The current invoice review could not be verified.", target)

    def _deadline(self, approval):
        try:
            deadline = parse_iso(approval["expires_at"])
            if deadline.utcoffset() is None:
                raise ValueError("missing time zone")
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            raise APRefusal(423, "invalid_authorization", "The match authorization deadline cannot be verified.", "approval") from exc
        if deadline <= self.now():
            raise ApprovalExpired("The match authorization expired.")

    def _installed_only(self, context, commitment):
        if self.c.db.one("SELECT id FROM procurement_awards WHERE commitment_id=?", (commitment["id"],)):
            raise APRefusal(422, "unsupported_purchase_order", "This practice workflow currently supports progress subcontracts.", "commitment")
        if any(not lot["withdrawn"] for lot in self.c.bills.lots(commitment["id"])):
            raise APRefusal(422, "unsupported_stored_material", "This practice workflow currently supports installed work without stored materials.", "commitment")
        prior = self.c.bills.latest(commitment["id"])
        if prior:
            self.contract.base._bill(context["authority"], prior["id"])

    def _matched_source(self, context, facts):
        if facts["basis"] != "progress":
            raise APRefusal(422, "unsupported_purchase_order", "This practice workflow currently supports progress subcontract matching.", "invoice")
        if facts.get("bill"):
            bill = self.contract.base._bill(context["authority"], facts["bill"]["id"])
            if bill["project_id"] != context["projectId"]:
                raise APRefusal(423, "invalid_record", "The invoice's source records cannot be verified.", "invoice")

    def _duplicate_request(self, invoice, manifest):
        rows = self.c.db.query("SELECT id FROM approvals WHERE operation=? AND subject_type='ap_invoice' AND subject_id=? AND status IN ('pending','granted') ORDER BY requested_at,id", (MATCH_OPERATION, invoice["id"]))
        for row in rows:
            approval_proof(self.c, row["id"])
            approval = self.c.approvals.get(row["id"])
            try:
                self._deadline(approval)
            except ApprovalExpired:
                continue
            if material_hash(manifest) == approval["material_hash"] and manifest.get("governance") == approval["manifest"].get("governance"):
                raise APRefusal(409, "duplicate_request", "This invoice already has a current match approval request.", row["id"])

    @staticmethod
    def _effects():
        return {"billStatus": None, "invoiceStatus": None, "approvalStatus": None, "matchStatus": None,
                "workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0, "journalPreview": [],
                "externalAccounting": "unavailable", "payment": "not_started", "matchExceptionCodes": [],
                "possibleDuplicate": False, "billLinked": False}

    def _evaluate(self, person_id, action, resource_id, typed):
        context = self.authorize(person_id, action, resource_id)
        version = self.contract.version(person_id, resource_id, RESOURCE_TYPES[action])
        record = context["record"]
        context["typed"] = typed
        checks = [self._check("person_authorized", "passed", "person", "The registered person holds the accountant duty in the project's current scope.")]
        effects, changes, refusal, manifest, plan = self._effects(), [], None, None, None
        approval = record if RESOURCE_TYPES[action] == "approval" else None
        invoice = self.ap.invoice(approval["subject_id"]) if approval else record if RESOURCE_TYPES[action] == "invoice" else None
        try:
            self.c.db.require_practice_mode()
            if action == "bill.prepare":
                self._installed_only(context, record)
                plan = self.c.bills.certification_preflight(commitment_id=record["id"], period_id=typed["periodId"],
                    installed=[{"sov_line_id": line["sovLineId"], "cumulative_installed": fmt(Decimal(line["cumulativeInstalledCents"]) / 100)} for line in typed["installed"]])
                if plan["content"]["stored_lots"] or money(plan["content"]["cumulative_stored"]):
                    raise APRefusal(422, "unsupported_stored_material", "This practice workflow currently supports installed work without stored materials.", "commitment")
                effects.update(billStatus="draft", amountDueCents=_cents(plan["content"]["amount_due"]),
                    retainageCents=_cents(plan["retainage_this_period"]), thisPeriodCents=_cents(plan["installed_this_period"]))
                checks.append(self._check("preparation_ready", "passed", "commitment", "Current SOV quantities and the open period produce this exact draft. No journal or payable is created."))
            elif action == "invoice.receive":
                self._installed_only(context, record)
                evidence = self.contract.evidence(person_id, typed["evidenceRevisionId"])
                if evidence["project_id"] != context["projectId"]:
                    raise APRefusal(404, "not_found", "This record is not available in the current project scope.", "evidenceRevisionId")
                if not evidence["is_current"]:
                    raise APRefusal(423, "evidence_stale", "Choose the current supplier invoice evidence revision.", "evidenceRevisionId")
                params = {"supplier_id": record["supplier_id"], "invoice_number": typed["invoiceNumber"], "invoice_date": typed["invoiceDate"],
                          "amount": fmt(Decimal(typed["amountCents"]) / 100), "evidence_hash": evidence["content_hash"],
                          "project_id": context["projectId"], "commitment_id": record["id"]}
                plan = self.ap.receive_preflight(**params)
                context.update(evidence=evidence, params=params)
                effects.update(invoiceStatus="received", amountCents=_cents(plan["content"]["amount"]), possibleDuplicate=plan["possible_duplicate"])
                checks.append(self._check("receipt_ready", "passed", "invoice", "The current source evidence and supplier terms produce this recorded invoice. Receipt creates no payable."))
                if plan["possible_duplicate"]:
                    checks.append(self._check("possible_duplicate", "warning", "invoice", "A possible duplicate will be recorded and must receive a separate documented review before matching."))
            elif action == "invoice.computeMatch":
                plan = self.ap.match_preflight(invoice["id"])
                self._matched_source(context, plan["facts"])
                effects.update(invoiceStatus="received", amountCents=_cents(invoice["amount"]),
                               matchStatus=plan["facts"]["status"], matchExceptionCodes=plan["facts"]["exceptions"])
                checks.append(self._check("match_computation_ready", "passed", "invoice", "This action records the current matching result. Linking the invoice requires a separate approved match."))
            elif action == "invoice.requestMatchApproval":
                manifest = self.c.check_request_approval(MATCH_OPERATION, invoice["id"], actor_role=context["duty"], requested_by=context["login"])
                self._duplicate_request(invoice, manifest)
                self._matched_source(context, self.ap._facts(self.ap._row(invoice["id"])))
                effects.update(invoiceStatus=invoice["status"], approvalStatus="pending", amountCents=_cents(invoice["amount"]))
                checks.append(self._check("match_request_ready", "passed", "invoice", "The current recorded match is eligible for a new independent accountant approval."))
            else:
                approval_proof(self.c, approval["id"])
                self._deadline(approval)
                if action == "invoice.approveMatch":
                    checked = self.c.check_invoice_match_grant(approval["id"], approver=context["login"], approver_role=context["duty"])
                    effects.update(approvalStatus="granted", invoiceStatus=invoice["status"], amountCents=_cents(invoice["amount"]))
                    checks.append(self._check("match_grant_ready", "passed", "approval", "An independent accountant may approve the unchanged match. Approval creates no journal, payable or invoice link."))
                else:
                    checked = self.c.check_invoice_match_execution(approval["id"], actor=context["login"])
                    effects.update(approvalStatus="consumed", invoiceStatus="matched", matchStatus="matched", amountCents=_cents(invoice["amount"]),
                                   billLinked=bool(checked["manifest"]["bindings"].get("bill")))
                    checks.append(self._check("match_execution_ready", "passed", "approval", "The intact grant permits this invoice link. Bill business approval and accounting posting remain separate actions."))
                manifest = checked["manifest"]
                self._matched_source(context, self.ap._facts(self.ap._row(invoice["id"])))
            context.update(manifest=manifest, plan=plan)
        except Exception as exc:
            if isinstance(exc, APRefusal) and exc.status == 404:
                # A reference outside the person's scope is unavailable, not a
                # reviewable blocked source with a disclosed existence.
                raise
            refusal = self._safe_refusal(exc, "approval" if approval else "commitment" if invoice is None else "invoice")
            checks.append(self._check(refusal.code, "blocked", refusal.target, refusal.message, "Refresh the record and review its current source and duties."))
            effects = self._effects()
        if approval:
            before = approval["manifest"]["amounts"].get("invoice_amount")
            if before is not None and _cents(before) != _cents(invoice["amount"]):
                changes.append({"field": "amountCents", "before": _cents(before), "after": _cents(invoice["amount"])})
            context["approval"] = approval
        if invoice:
            context["invoice"] = invoice
        fingerprint = None
        if refusal is None:
            facts = {"workspace": self.c.db.mode_status(), "personId": context["personId"], "login": context["login"],
                     "duty": context["duty"], "scope": context["authority"].scope_hash,
                     "action": action, "resourceId": resource_id, "version": version, "body": typed,
                     "material": material_part(manifest) if manifest else None,
                     "governance": manifest.get("governance") if manifest else None,
                     "approval": approval, "plan": plan, "effects": effects}
            digest = hmac.new(self.secret, canonical_json(facts).encode(), sha256).digest()
            fingerprint = "ipf1." + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        review = {"action": action, "resourceId": resource_id, "resourceVersion": version, "version": version,
                  "allowed": refusal is None, "checks": checks, "changes": changes, "safeEffects": effects, "fingerprint": fingerprint}
        return context, review, refusal
