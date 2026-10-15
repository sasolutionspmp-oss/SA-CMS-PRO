"""Scoped exact owner-billing reads for the disposable human AR workflow.

Private source, original approval and journal proofs establish each admitted
record. DTOs retain original grant/post/send outcomes separately from current
bill and standing balance state. No staff sign-in or external delivery is implied.
"""
from __future__ import annotations

import base64
from datetime import date
from functools import wraps
from hashlib import sha256
import hmac
import json
from urllib.parse import quote

from .ap_contract import APRefusal
from .core.ids import canonical_json, hash_json, parse_iso, utcnow
from .core.money import money
from .ar_sessions import ARIdentityRefusal, authority_for
from .ar_wire import ACTION_ROUTES, AGING_ROUTES, COLLECTIONS, MAX_CENTS, PROVENANCE, dated_query
from .core.approvals import StaleApprovalError, material_hash
from .domain.owner_billing import OwnerBillingError


API_PREFIX = "/api/ar-practice/v1/"


def _missing():
    raise APRefusal(404, "not_found", "The record is unavailable in this AR session.", "record")


def _read(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.cipher.db._lock:
            try:
                return method(self, *args, **kwargs)
            except APRefusal:
                raise
            except ARIdentityRefusal as exc:
                raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
            except Exception:
                raise APRefusal(423, "owner_billing_source_unavailable", "The owner-billing source could not be verified.", "record") from None
    return wrapped


def _cents(value):
    result = int(money(value) * 100)
    if abs(result) > MAX_CENTS:
        raise ValueError("Owner-billing display amount exceeds its exact range")
    return result


class ARContract:
    def __init__(self, cipher, *, secret):
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("AR contract requires an owned private signing key")
        self.cipher, self.secret = cipher, secret

    def _authority(self, person_id, *, resource=False):
        self.cipher.db.require_practice_mode()
        try:
            authority = authority_for(self.cipher, person_id)
            if not authority.project_ids:
                if resource:
                    _missing()
                raise APRefusal(403, "ar_duty_required", "This AR view requires a current owned project duty.", "duty")
            return authority
        except ARIdentityRefusal as exc:
            raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None

    @property
    def domain(self):
        return self.cipher.plugin("owner_billing")

    def _scope(self, authority, identifier, kind):
        if kind == "basis":
            try:
                record = self.domain.basis_scope(identifier)
            except OwnerBillingError:
                _missing()
        elif kind == "bill":
            try:
                record = self.domain.source_scope(identifier)
            except OwnerBillingError:
                _missing()
        elif kind in ("businessApproval", "sendApproval"):
            operation = "prime_bill.approve" if kind == "businessApproval" else "prime_bill.send"
            record = self.cipher.db.one("""SELECT a.id,a.subject_id AS billId,b.project_id AS projectId
                FROM approvals a JOIN prime_bills b ON b.id=a.subject_id
                WHERE a.id=? AND a.operation=? AND a.subject_type='prime_bill'""", (identifier, operation))
            if record is not None and record["projectId"] in authority.project_ids:
                classified = self.domain.source_scope(record["billId"])
                if classified is None or classified["projectId"] != record["projectId"]:
                    _missing()
        else:
            raise APRefusal(422, "unsupported_resource", "Choose a fixed owner-billing record.", "record")
        if record is None or record["projectId"] not in authority.project_ids:
            _missing()
        if kind == "bill" and not self.domain.is_modern(identifier):
            _missing()
        return {"id": identifier, **record}

    @_read
    def authorize(self, person_id, action, resource_id):
        authority = self._authority(person_id, resource=True)
        definition = next((route for route in ACTION_ROUTES if route.action == action), None)
        if definition is None:
            raise APRefusal(422, "unsupported_action", "Choose a fixed owner-billing action.", "action")
        record = self._scope(authority, resource_id, definition.resource_type)
        authority.require(record["projectId"], definition.duty)
        operation_role = ("accountant" if action == "ownerBill.requestApproval"
                          else authority.operation_role(record["projectId"], definition.duty))
        return {"personId": authority.person_id, "login": authority.login, "duty": definition.duty,
                "operationRole": operation_role, "authority": authority, "projectId": record["projectId"], "record": record}

    def _person(self, login):
        if login is None:
            return None
        value = self.cipher.plugin("people").person_for(login)
        if value is None:
            raise ValueError("The original recorded person is unavailable")
        return {"id": value["id"], "displayName": value["display_name"]}

    def _project(self, project_id):
        value = self.cipher.project(project_id)
        return {"id": value["id"], "name": value["name"]}

    def _period(self, period_id):
        value = self.cipher.ledger.period(period_id)
        return {"id": value["id"], "name": value["name"], "startDate": value["start_date"],
                "endDate": value["end_date"], "status": value["status"]}

    def _document(self, revision_id, *, project_id):
        row = self.cipher.db.one("""SELECT r.id FROM document_revisions r JOIN documents d ON d.id=r.document_id
                                    WHERE r.id=? AND d.project_id=?""", (revision_id, project_id))
        if row is None:
            raise ValueError("Owned source document is unavailable")
        revision = self.cipher.evidence.revision(revision_id)
        document = self.cipher.evidence.document(revision["document_id"])
        return {"documentId": document["id"], "revisionId": revision["id"], "title": document["title"],
                "kind": document["kind"], "revision": revision["revision"], "current": revision["is_current"]}

    def _token(self, value):
        return "arv1:" + hmac.new(self.secret, canonical_json(value).encode(), sha256).hexdigest()

    def _inventories(self, project_ids):
        # Called only after resolving the caller's actual current authority and
        # minimal scope. Native original financial proof does not certify API history.
        from .ar_receipts import ar_receipt_inventory_proof
        ar_receipt_inventory_proof(self.cipher.db, self.cipher.audit)
        for project_id in project_ids:
            self.domain.require_current_project_finance(project_id)
        bases = self.domain.basis_inventory(project_ids=tuple(project_ids))
        sources = self.domain.source_inventory(project_ids=tuple(project_ids))
        return bases, sources

    @_read
    def version(self, person_id, resource_id, resource_type):
        authority = self._authority(person_id, resource=True)
        scoped = self._scope(authority, resource_id, resource_type)
        bases, sources = self._inventories((scoped["projectId"],))
        approvals = self._approval_inventory((scoped["projectId"],))
        grants = self.domain.grant_inventory(project_ids=(scoped["projectId"],))
        postings = [self.domain.posting_receipt(source["bill"]["id"]) for source in sources]
        sends = [self.domain.send_proof(source["bill"]["id"]) for source in sources]
        settings = [self.domain._settings_history(basis["record"]["customer_id"]) for basis in bases]
        documents = self._evidence_inventory((scoped["projectId"],))
        periods = []
        for period in self.cipher.ledger.periods():
            self.domain._period(period["id"])
            periods.append(self._period(period["id"]))
        value = {"provenance": PROVENANCE, "workspace": self.cipher.db.mode_status(),
                 "authority": self.cipher.db.authority_status(), "personId": authority.person_id,
                 "scopeHash": authority.scope_hash, "resourceType": resource_type, "resourceId": resource_id,
                 "bases": bases, "sources": sources, "approvals": approvals, "grants": grants,
                 "postings": postings, "sends": sends, "settings": settings, "documents": documents,
                 "periods": periods, "policy": self.cipher.plugin("people").current_policy()}
        return self._token(value)

    def _approval_inventory(self, project_ids):
        return self.domain.approval_inventory(project_ids=tuple(project_ids))

    def _evidence_inventory(self, project_ids):
        if not project_ids:
            return []
        kinds = ("owner_agreement", "owner_claim", "owner_certification")
        scopes = tuple(project_ids)
        marks = ",".join("?" for _ in scopes)
        rows = self.cipher.db.query(f"SELECT * FROM documents WHERE project_id IN ({marks}) AND kind IN (?,?,?) ORDER BY id",
                                    (*scopes, *kinds))
        expected = []
        for event in self.cipher.db.query("SELECT * FROM audit_log WHERE action='document.registered' AND entity_type='document' ORDER BY seq"):
            payload = json.loads(event["payload_json"])
            if payload.get("project_id") in scopes and payload.get("kind") in kinds:
                expected.append(event["entity_id"])
        if len(set(expected)) != len(expected) or set(expected) != {row["id"] for row in rows}:
            raise ValueError("The scoped owner evidence birth inventory changed")
        result = []
        for row in rows:
            revisions = self.cipher.db.query("SELECT id FROM document_revisions WHERE document_id=? ORDER BY revision", (row["id"],))
            if not revisions:
                raise ValueError("Owned source has no original revision")
            proofs = [self.domain._document(revision["id"], row["project_id"], row["kind"]) for revision in revisions]
            result.append({"document": row, "revisions": proofs})
        return result

    def _actions(self, authority, project_id, candidates, identifier):
        from .ar_preflight import ARPreflight
        preflight = ARPreflight(self.cipher, self, secret=self.secret)
        allowed, blocked = [], []
        for action in candidates:
            definition = next(route for route in ACTION_ROUTES if route.action == action)
            if not authority.allows(project_id, definition.duty):
                continue
            review = preflight.review(authority.person_id, action, identifier, {})
            if review["allowed"]:
                allowed.append(action)
            else:
                blocked.extend(check for check in review["checks"] if check["status"] == "blocked")
        return allowed, blocked

    def _source_status(self, basis_id):
        try:
            self.domain.basis_proof(basis_id, current=True)
            return "current"
        except StaleApprovalError:
            return "stale"

    @staticmethod
    def _sov_line(line):
        return {"lineId": line["line_id"], "description": line["description"], "basis": line["basis"],
                "scheduledAmountCents": line["scheduled_amount_cents"], "unit": line["unit"],
                "contractQuantity": line["contract_quantity"], "unitPriceCents": line["unit_price_cents"]}

    def _basis(self, authority, proof):
        body = proof["record"]
        project_id = proof["projectId"]
        source_status = self._source_status(body["id"])
        sources = self.domain.source_inventory(project_ids=(project_id,))
        complete = not any(source["bill"]["status"] in ("draft", "void", "reversed") for source in sources)
        return {**PROVENANCE, "id": body["id"], "version": self.version(authority.person_id, body["id"], "basis"),
                "project": self._project(project_id), "customer": {"id": body["customer_id"], "name": body["scope"]["customerName"]},
                "contractValueCents": _cents(body["contract"]["record"]["contract_value"]),
                "retainageRate": body["contract"]["record"]["retainage_rate"], "termsDays": body["terms"]["days"],
                "agreementSource": self._document(body["agreement"]["revision"]["id"], project_id=project_id),
                "sov": [self._sov_line(line) for line in body["sov"]], "sourceStatus": source_status,
                "declaration": body["declaration"],
                "availableActions": ["ownerBill.prepare"] if source_status == "current" and complete and authority.allows(project_id, "pm") else []}

    @_read
    def preparation(self, person_id, basis_id):
        authority = self._authority(person_id, resource=True)
        scoped = self._scope(authority, basis_id, "basis")
        proof = self.domain.basis_proof(basis_id)
        basis = self._basis(authority, proof)
        project_id = scoped["projectId"]
        documents = self._evidence_inventory((project_id,))
        choices = {"owner_claim": [], "owner_certification": []}
        for source in documents:
            if source["document"]["kind"] in choices:
                selected = source["revisions"][-1]["revision"]["id"]
                choices[source["document"]["kind"]].append(self._document(selected, project_id=project_id))
        periods = []
        today = self.cipher.receivables._today().isoformat()
        for period in self.cipher.ledger.periods():
            self.domain._period(period["id"])
            if period["status"] == "open" and period["start_date"] <= today:
                periods.append(self._period(period["id"]))
        sources = self.domain.source_inventory(project_ids=(project_id,))
        standing = [source for source in sources if source["bill"]["status"] in ("posted", "sent", "collected")]
        previous = max(standing, key=lambda source: source["bill"]["sequence"]) if standing else None
        lines = {line["lineId"]: line for line in previous["calculation"]["lines"]} if previous else {}
        return {**PROVENANCE, "version": basis["version"], "basis": basis,
                "claimSources": choices["owner_claim"], "reviewSources": choices["owner_certification"], "periods": periods,
                "previous": {"billId": previous["bill"]["id"] if previous else None,
                    "certifiedCents": previous["calculation"]["reviewedCertifiedCents"] if previous else 0,
                    "retainedCents": previous["calculation"]["retainedCumulativeCents"] if previous else 0,
                    "lines": [{"lineId": line["lineId"],
                        "reviewedQuantity": lines[line["lineId"]]["reviewedQuantity"] if line["lineId"] in lines
                            else "0" if line["basis"] == "unitPrice" else None,
                        "reviewedAmountCents": lines[line["lineId"]]["reviewedAmountCents"] if line["lineId"] in lines else 0}
                        for line in basis["sov"]]}, "availableActions": basis["availableActions"]}

    def _grant(self, bill_id, project_id):
        rows = [proof["record"] for proof in self.domain.grant_inventory(project_ids=(project_id,))
                if proof["record"]["prime_bill_id"] == bill_id]
        if not rows:
            return None
        grant = self.domain.grant_proof(bill_id, approval_id=rows[-1]["approval_id"])
        body, approval = grant["record"], grant["approval"]
        return {"id": body["id"], "approvalId": body["approval_id"], "status": "granted",
                "authorizationStatus": approval["status"], "requestedBy": self._person(approval["requested_by"]),
                "reviewedBy": self._person(body["reviewedBy"]), "reviewedAt": body["createdAt"]}

    def _posting(self, bill_id):
        body = self.domain.posting_receipt(bill_id)
        if body is None:
            return None
        return {"receiptId": body["id"], "journalId": body["journal"]["header"]["id"],
                "period": self._period(body["period"]["id"]), "postedBy": self._person(body["actor"]), "postedAt": body["createdAt"],
                "journalPreview": [{"accountCode": line["account_code"], "debitCents": _cents(line["debit"]),
                                    "creditCents": _cents(line["credit"]), "memo": line["memo"]} for line in body["journal"]["lines"]]}

    def _send(self, bill_id):
        proof = self.domain.send_proof(bill_id)
        if proof is None:
            return None
        body = proof["record"]
        return {"id": body["id"], "status": "sent_to_synthetic_sink", "channel": "mail-sink", "sentAt": body["sent_at"],
                "sentBy": self._person(body["sent_by"]), "recipients": body["recipients"], "externalDelivery": False}

    def _approval_status(self, approval):
        if approval["status"] in ("pending", "granted") and parse_iso(approval["expires_at"]) <= utcnow():
            return "expired"
        return approval["status"]

    @_read
    def bill(self, person_id, bill_id):
        authority = self._authority(person_id, resource=True)
        scoped = self._scope(authority, bill_id, "bill")
        current_finance = self.domain.current_ar_proof(bill_id)
        proof = current_finance["source"]
        body, bill, basis, calculation = proof["record"], proof["bill"], proof["basis"]["record"], proof["calculation"]
        bill = current_finance["currentBill"]
        project_id = scoped["projectId"]
        grant = self._grant(bill_id, project_id)
        posting, send = self._posting(bill_id), self._send(bill_id)
        approvals = [value["approval"] for value in self._approval_inventory((project_id,)) if value["approval"]["subject_id"] == bill_id
                     and value["approval"]["operation"] == "prime_bill.approve"]
        effective = bill["status"]
        if bill["status"] == "draft":
            source_changed = (not self.cipher.evidence.is_current(body["claim"]["revision"]["id"])
                              or not self.cipher.evidence.is_current(body["review"]["revision"]["id"]))
            if self._source_status(basis["id"]) == "stale" or bill["chain_stale"] or bill["contract_stale"] or source_changed:
                effective = "stale"
            elif approvals and self._approval_status(approvals[-1]) == "granted":
                effective = "approved_not_posted"
            elif approvals and self._approval_status(approvals[-1]) == "pending":
                effective = "under_review"
        elif bill["status"] in ("posted", "sent", "collected"):
            effective = "settled" if bill["settled"] else "sent_open" if send else "posted_awaiting_send"
        actions, blocked = self._actions(authority, project_id,
            ("ownerBill.requestApproval", "ownerBill.post", "ownerBill.requestSend"), bill_id)
        locators = {line["lineId"]: line for line in body["locators"]}
        lines = [{**line, "claimSourceLocator": locators[line["lineId"]]["claimSourceLocator"],
                  "reviewSourceLocator": locators[line["lineId"]]["reviewSourceLocator"]} for line in calculation["lines"]]
        totals = {key: calculation[key] for key in ("priorCertifiedCents", "claimedCertifiedCents", "reviewedCertifiedCents",
            "revenueThisPeriodCents", "retainageThisPeriodCents", "retainedCumulativeCents", "amountDueCents")}
        totals.update(currentOpenCents=_cents(bill["open"]), currentReceivedCents=_cents(bill["received"]),
            currentCreditedCents=_cents(money(bill["credited_by_memo"]) + money(bill["credited_by_reversal"])),
            currentWrittenOffCents=_cents(bill["written_off"]), currentDepositsAppliedCents=_cents(bill["deposits_applied"]))
        related = [{"type": "basis", "id": basis["id"], "title": "Original owner billing basis",
                    "apiRoute": API_PREFIX + "owner-bases/" + quote(basis["id"], safe="") + "/preparation"}]
        for approval in self._approval_inventory((project_id,)):
            original = approval["approval"]
            if original["subject_id"] == bill_id:
                financial = original["operation"] == "prime_bill.approve"
                related.append({"type": "approval" if financial else "sendApproval", "id": original["id"],
                    "title": "Original financial review" if financial else "Synthetic send review",
                    "apiRoute": API_PREFIX + ("owner-bill-approvals/" if financial else "owner-send-approvals/") + quote(original["id"], safe="") + "/packet"})
        return {**PROVENANCE, "id": bill_id, "version": self.version(person_id, bill_id, "bill"),
                "project": self._project(project_id), "customer": {"id": bill["customer_id"], "name": basis["scope"]["customerName"]},
                "sequence": bill["sequence"], "status": bill["status"], "effectiveStatus": effective,
                "certificationPeriod": self._period(bill["period_id"]), "invoiceDate": bill["invoice_date"],
                "dueDate": bill["due_date"], "termsDays": bill["payment_terms_days"],
                "basis": {"id": basis["id"], "agreementSource": self._document(basis["agreement"]["revision"]["id"], project_id=project_id)},
                "claimSource": self._document(body["claim"]["revision"]["id"], project_id=project_id),
                "reviewSource": self._document(body["review"]["revision"]["id"], project_id=project_id),
                "lines": lines, "totals": totals, "businessApproval": grant, "posting": posting, "send": send,
                "availableActions": actions, "blockedReasons": blocked, "relatedRecords": related,
                "officialBooks": "unavailable", "externalSettlement": False}

    def _approval(self, authority, proof):
        approval = proof["approval"]
        bill_id = approval["subject_id"]
        scoped = self._scope(authority, bill_id, "bill")
        source = self.domain.current_ar_proof(bill_id)["source"]
        financial = approval["operation"] == "prime_bill.approve"
        kind = "businessApproval" if financial else "sendApproval"
        effective = self._approval_status(approval)
        if effective in ("pending", "granted"):
            try:
                current = self.cipher._manifest(approval["operation"], bill_id, approval["actor_role"])
                if (material_hash(current) != approval["material_hash"]
                        or canonical_json(current.get("governance")) != canonical_json(approval["manifest"].get("governance"))):
                    effective = "stale"
            except (RuntimeError, ValueError):
                effective = "stale"
        actions, blocked = self._actions(authority, scoped["projectId"],
            ("ownerBill.approve",) if financial else ("ownerBill.approveSend", "ownerBill.send"), approval["id"])
        return {**PROVENANCE, "id": approval["id"], "version": self.version(authority.person_id, approval["id"], kind),
                "type": "business" if financial else "send", "billId": bill_id, "project": self._project(scoped["projectId"]),
                "sequence": source["bill"]["sequence"], "status": approval["status"], "effectiveStatus": effective,
                "requestedBy": self._person(approval["requested_by"]), "approvedBy": self._person(approval["approver"]),
                "requestedAt": approval["requested_at"], "approvedAt": approval["granted_at"], "expiresAt": approval["expires_at"],
                "availableActions": actions, "blockedReasons": blocked}

    @_read
    def packet(self, person_id, approval_id):
        return self._packet(person_id, approval_id, financial=True)

    @_read
    def send_packet(self, person_id, approval_id):
        return self._packet(person_id, approval_id, financial=False)

    def _packet(self, person_id, approval_id, *, financial):
        authority = self._authority(person_id, resource=True)
        kind = "businessApproval" if financial else "sendApproval"
        scoped = self._scope(authority, approval_id, kind)
        approval = self._approval(authority, self.domain.approval_proof(approval_id))
        return {**PROVENANCE, "id": approval_id, "version": self.version(person_id, approval_id, kind),
                "approval": approval, "bill": self.bill(person_id, scoped["billId"]),
                "availableActions": approval["availableActions"], "blockedReasons": approval["blockedReasons"]}

    @_read
    def send_preparation(self, person_id, bill_id):
        authority = self._authority(person_id, resource=True)
        scoped = self._scope(authority, bill_id, "bill")
        current_finance = self.domain.current_ar_proof(bill_id)
        source, current_bill = current_finance["source"], current_finance["currentBill"]
        self.domain._settings_history(source["bill"]["customer_id"])
        recipients = self.cipher.receivables.billing_recipients(source["bill"]["customer_id"])
        actions, blocked = self._actions(authority, scoped["projectId"], ("ownerBill.requestSend",), bill_id)
        return {**PROVENANCE, "id": bill_id, "version": self.version(person_id, bill_id, "bill"),
                "bill": self.bill(person_id, bill_id), "delivery": {"channel": "mail-sink", "recipients": recipients["recipients"],
                    "amountDueCents": _cents(current_bill["amount_due"]), "balanceDueCents": _cents(current_bill["open"]),
                    "externalDelivery": False}, "availableActions": actions, "blockedReasons": blocked}

    def _page(self, authority, collection, items, *, project_id=None, status=None, search=None, top=50, cursor=None, extra=None):
        if type(top) is not int or not 1 <= top <= 50:
            raise APRefusal(422, "invalid_query", "Choose a page size from 1 through 50.", "top")
        facets = []
        for value in sorted({item.get("effectiveStatus", item.get("status")) for item in items} - {None}):
            facets.append({"value": value, "count": sum(item.get("effectiveStatus", item.get("status")) == value for item in items)})
        if status is not None:
            items = [item for item in items if item.get("effectiveStatus", item.get("status")) == status]
        if search is not None:
            if type(search) is not str or not search.strip() or len(search) > 2048:
                raise APRefusal(422, "invalid_query", "Use bounded text for this search.", "search")
            needle = search.casefold()
            items = [item for item in items if needle in canonical_json(item).casefold()]
        items = sorted(items, key=lambda item: (item.get("project", {}).get("name", ""), item.get("sequence", 0), item.get("id", item.get("billId", ""))))
        binding = hash_json({"personId": authority.person_id, "scopeHash": authority.scope_hash, "collection": collection,
                             "projectId": project_id, "status": status, "search": search, "top": top, "items": items, "extra": extra})
        offset = 0
        if cursor is not None:
            try:
                encoded, signature = cursor.split(".")
                raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                value = json.loads(raw)
                if (not hmac.compare_digest(signature, hmac.new(self.secret, raw, sha256).hexdigest())
                        or value["binding"] != binding or type(value["offset"]) is not int or value["offset"] < 0):
                    raise ValueError
                offset = value["offset"]
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise APRefusal(422, "invalid_cursor", "Refresh this AR view before paging.", "cursor") from None
        next_cursor = None
        if offset + top < len(items):
            raw = canonical_json({"binding": binding, "offset": offset + top}).encode()
            next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + hmac.new(self.secret, raw, sha256).hexdigest()
        totals = {}
        additive = {"contractValueCents", "revenueThisPeriodCents", "retainageThisPeriodCents", "amountDueCents",
                    "currentOpenCents", "currentReceivedCents", "currentCreditedCents", "currentWrittenOffCents",
                    "currentDepositsAppliedCents", "retainedCents", "releasedCents"}
        for item in items:
            for key, value in (item.get("totals") or item).items():
                if key in additive and type(value) is int:
                    totals[key] = totals.get(key, 0) + value
        if any(abs(value) > MAX_CENTS for value in totals.values()):
            raise APRefusal(422, "invalid_total", "The selected exact total exceeds the display range.", "totals")
        return {**PROVENANCE, "items": items[offset:offset + top], "count": len(items), "nextCursor": next_cursor,
                "facets": {"statuses": facets}, "totals": totals}

    @_read
    def read(self, person_id, collection, *, project_id=None, status=None, search=None, top=50, cursor=None):
        authority = self._authority(person_id)
        if collection not in COLLECTIONS:
            raise APRefusal(404, "route_not_found", "This AR view is unavailable.")
        if project_id is not None and project_id not in authority.project_ids:
            _missing()
        projects = (project_id,) if project_id is not None else authority.project_ids
        if collection != "projects":
            for identifier in projects:
                self.domain.require_current_project_finance(identifier)
        if collection == "projects":
            items = [{**PROVENANCE, **self._project(identifier)} for identifier in projects]
        elif collection == "owner-bases":
            items = [self._basis(authority, proof) for proof in self.domain.basis_inventory(project_ids=projects)]
        elif collection == "owner-bills":
            items = [self.bill(person_id, proof["bill"]["id"]) for proof in self.domain.source_inventory(project_ids=projects)]
        else:
            financial = collection == "owner-bill-approvals"
            items = [self._approval(authority, proof) for proof in self._approval_inventory(projects)
                     if (proof["approval"]["operation"] == "prime_bill.approve") == financial]
        return self._page(authority, collection, items, project_id=project_id, status=status, search=search, top=top, cursor=cursor)

    @_read
    def aging(self, person_id, collection, *, project_id=None, as_of=None, search=None, top=50, cursor=None):
        authority = self._authority(person_id, resource=True)
        if collection not in AGING_ROUTES:
            raise APRefusal(404, "route_not_found", "This AR aging view is unavailable.")
        if project_id is not None and project_id not in authority.project_ids:
            _missing()
        projects = (project_id,) if project_id is not None else authority.project_ids
        as_of_day = dated_query(self.cipher.receivables._today().isoformat() if as_of is None else as_of)
        items, subledger, control = [], 0, 0
        for identifier in projects:
            bases, sources = self._inventories((identifier,))
            if not bases:
                continue
            # Prove every admitted source and original financial outcome before
            # reading or totaling the current standing native subledger.
            for source in sources:
                self.domain.posting_receipt(source["bill"]["id"])
                self.domain.send_proof(source["bill"]["id"])
            proofs = {source["bill"]["id"]: source for source in sources}
            result = (self.cipher.receivables.ar_open_items(identifier, as_of=as_of_day) if collection == "ar-aging"
                      else self.cipher.receivables.retainage_receivable_items(identifier))
            if result["errors"] or result["reconciled"] is not True:
                raise ValueError("The scoped standing AR subledger does not reconcile")
            subledger += _cents(result["subledger_total"])
            control += _cents(result["control_balance"])
            basis = bases[0]["record"]
            customer = {"id": basis["customer_id"], "name": basis["scope"]["customerName"]}
            if collection == "retainage-aging":
                for item in result["items"]:
                    if item["project_id"] != identifier:
                        raise ValueError("Native retained AR escaped the requested scope")
                    items.append({"project": self._project(identifier), "customer": customer,
                        "throughSequence": item["through_sequence"], "retainedCents": _cents(item["retained"]),
                        "releasedCents": _cents(item["released"]), "currentOpenCents": _cents(item["open"]),
                        "billIds": sorted(proofs), "agingBucket": "unreleased", "dueDate": None, "daysPastDue": None})
            else:
                for item in result["items"]:
                    if item.get("kind") != "prime_bill" or item.get("prime_bill_id") not in proofs or item["project_id"] != identifier:
                        raise ValueError("An AR source has no admitted owner-billing source proof")
                    days = item["days_past_due"]
                    bucket = ("undated" if days is None else "current" if days <= 0 else "1_30" if days <= 30
                              else "31_60" if days <= 60 else "61_90" if days <= 90 else "over_90")
                    items.append({"billId": item["prime_bill_id"], "project": self._project(identifier), "customer": customer,
                        "sequence": item["sequence"], "invoiceDate": item["invoice_date"], "dueDate": item["due_date"],
                        "daysPastDue": days, "currentOpenCents": _cents(item["open"]), "agingBucket": bucket})
        if abs(subledger) > MAX_CENTS or abs(control) > MAX_CENTS:
            raise ValueError("The scoped AR reconciliation exceeds the exact display range")
        result = self._page(authority, collection, items, project_id=project_id, search=search, top=top, cursor=cursor,
                            extra={"agingAsOf": as_of_day, "balanceBasis": "current_standing_balance"})
        return {**result, "agingAsOf": as_of_day, "balanceBasis": "current_standing_balance", "historicalSnapshot": False,
                "workingLedger": True, "watermark": "Working ledger, not for issue", "scope": "owner_billing",
                "reconciliation": {"scope": "authorized_projects", "subledgerCents": subledger,
                                   "controlCents": control, "reconciled": subledger == control}}
