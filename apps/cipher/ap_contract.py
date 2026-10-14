"""Scoped, typed reads for the disposable human AP practice workflow.

Every public read derives authority from the audited registry again. These
presenters use explicit display/economic fields; private source proofs are used
only for integrity and opaque version bindings. They never open or seed a DB.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from functools import wraps
from typing import Any, TYPE_CHECKING, Literal, TypedDict

from .api_contract import PracticeReadRefusal, _cents, _require_practice, _totals, _validate
from .core.approvals import ApprovalError, material_hash, material_part
from .core.ids import canonical_json, hash_json, loads, parse_iso, utcnow
from .core.money import fmt, money, rate
from .domain.bills import BillError
from .domain.commitments import CommitmentError

if TYPE_CHECKING:
    from .service import Cipher

CONTRACT_VERSION = "cipher.ap-practice.v1"
PROVENANCE = {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "currency": "USD"}
CAPABILITIES = {"sessionIdentity": "registered_synthetic_person", "scopedReads": True,
                "microsoftSignIn": False, "liveAdmission": False, "externalAccounting": "unavailable",
                "commands": ["bill.requestApproval", "bill.approve", "bill.post"]}
_ACTIONS = ("bill.requestApproval", "bill.approve", "bill.post")


class PersonRead(TypedDict):
    id: str
    displayName: str


class PeriodRead(TypedDict):
    id: str
    name: str
    startDate: str
    endDate: str
    status: str


class BillLineRead(TypedDict):
    id: str
    sovLineId: str
    description: str
    costCode: str
    cumulativeInstalledCents: int
    priorInstalledCents: int
    thisPeriodInstalledCents: int


class BusinessApprovalRead(TypedDict):
    id: str | None
    approvalId: str
    status: str
    effectiveStatus: str
    requestedBy: PersonRead
    approvedBy: PersonRead | None
    requestedAt: str
    approvedAt: str | None
    expiresAt: str


class PostingRead(TypedDict):
    receiptId: str
    journalIds: list[str]
    period: PeriodRead
    postedBy: PersonRead
    postedAt: str
    reason: str


class BillRecord(TypedDict):
    id: str
    version: str
    projectId: str
    commitmentId: str
    supplierId: str
    projectName: str
    commitmentTitle: str
    supplierName: str
    sequence: int
    displayNumber: Literal[None]
    status: str
    effectiveStatus: str
    certificationPeriod: PeriodRead
    amountDueCents: int
    currentDueCents: int
    retainageCents: int
    thisPeriodCents: int
    lines: list[BillLineRead]
    businessApproval: BusinessApprovalRead | None
    posting: PostingRead | None
    postingPeriods: list[PeriodRead]
    availableActions: list[str]
    blockedReasons: list[dict[str, str | None]]


class APRefusal(ValueError):
    """A controlled error whose message and fields are safe for an API response."""

    def __init__(self, status: int, code: str, message: str, target: str | None = None):
        self.status, self.code, self.message, self.target = status, code, message, target
        self.value = {"code": code, "message": message, "target": target}
        super().__init__(message)


def _not_found() -> None:
    raise APRefusal(404, "not_found", "The record is unavailable in this practice session.", "record")


def _invalid_record() -> None:
    raise APRefusal(422, "invalid_record", "The record's source evidence could not be verified.", "record")


def _money(value: Any) -> int:
    try:
        return _cents(value)
    except PracticeReadRefusal as exc:
        raise APRefusal(422, exc.code, exc.message, exc.target) from None


def _locked(method):
    """Keep scope, source reads and serialization in one consistent DB view."""
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.cipher.db._lock:
            return method(self, *args, **kwargs)
    return run


class APContract:
    def __init__(self, cipher: Cipher, *, secret: bytes):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("AP contract requires a server-owned signing key of at least 32 bytes.")
        self.cipher, self.secret = cipher, secret

    def _authority(self, person_id: str):
        from .ap_sessions import APIdentityRefusal, authority_for
        try:
            _require_practice(self.cipher)
            authority = authority_for(self.cipher, person_id)
            if not self.cipher.audit.verify_chain()["ok"]:
                raise APRefusal(423, "workspace_unavailable", "Practice workspace evidence could not be verified.", "workspace")
            return authority
        except APIdentityRefusal as exc:
            raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
        except PracticeReadRefusal as exc:
            raise APRefusal(423, exc.code, exc.message, exc.target) from None

    def _person(self, login: str | None) -> PersonRead | None:
        if login is None:
            return None
        p = self.cipher.plugin("people").person_for(login)
        if p is None:
            _invalid_record()
        return {"id": p["id"], "displayName": p["display_name"]}

    def _period(self, period_id: str) -> PeriodRead:
        row = self.cipher.db.one("SELECT id,name,start_date,end_date,status FROM periods WHERE id=?", (period_id,))
        if row is None:
            _invalid_record()
        return {"id": row["id"], "name": row["name"], "startDate": row["start_date"],
                "endDate": row["end_date"], "status": row["status"]}

    def _consumed_source(self, approval_id: str, operation: str, subject_type: str, subject_id: str) -> dict[str, Any]:
        approval = self.cipher.approvals.get(approval_id)
        manifest = approval["manifest"]
        if (approval["status"] != "consumed" or approval["operation"] != operation
                or approval["subject_type"] != subject_type or approval["subject_id"] != subject_id
                or manifest.get("operation") != operation or manifest.get("subject") != {"type": subject_type, "id": subject_id}
                or approval["manifest_hash"] != hash_json(manifest) or approval["material_hash"] != material_hash(manifest)):
            _invalid_record()
        events = self.cipher.db.query("SELECT action,actor,payload_json FROM audit_log WHERE entity_type='approval' AND entity_id=? ORDER BY seq", (approval_id,))
        if any(event["action"] in ("approval.expired", "approval.invalidated") for event in events):
            _invalid_record()
        for action, actor, key, expected in (("requested", approval["requested_by"], "manifest_hash", approval["manifest_hash"]),
                                           ("granted", approval["approver"], "material_hash", approval["material_hash"]),
                                           ("consumed", approval["consumed_by"], "material_hash", approval["material_hash"])):
            matching = [event for event in events if event["action"] == "approval." + action]
            if len(matching) != 1 or matching[0]["actor"] != actor:
                _invalid_record()
            payload = loads(matching[0]["payload_json"])
            if payload.get(key) != expected or payload.get("operation") != operation:
                _invalid_record()
        return manifest

    def _commitment(self, commitment_id: str) -> dict[str, Any]:
        """Reconcile exposed commitment money/scope to audited execution sources."""
        try:
            row = self.cipher.commitments.get(commitment_id)
            created = self.cipher.db.query("SELECT payload_json FROM audit_log WHERE action='commitment.created' AND entity_type='commitment' AND entity_id=?", (commitment_id,))
            if len(created) != 1:
                _invalid_record()
            origin = loads(created[0]["payload_json"])
            if any(origin.get(key) != row[key] for key in ("project_id", "supplier_id", "estimate_id", "original_amount")):
                _invalid_record()
            execution = self.cipher.db.query("SELECT payload_json FROM audit_log WHERE action='commitment.executed' AND entity_type='commitment' AND entity_id=?", (commitment_id,))
            if row["status"] not in ("executed", "closed"):
                if execution or row["approval_id"]:
                    _invalid_record()
                if row["version"] != 1 or row["executed_amount"] != row["original_amount"] or _money(row["sov_total"]) != _money(row["original_amount"]):
                    _invalid_record()
                return row
            if len(execution) != 1:
                _invalid_record()
            source = self._consumed_source(row["approval_id"], "commitment.execute", "commitment", commitment_id)
            executed = loads(execution[0]["payload_json"])
            project_scope = self.cipher.db.one("SELECT entity,currency FROM projects WHERE id=?", (row["project_id"],))
            if (executed.get("approval_id") != row["approval_id"] or executed.get("amount") != row["original_amount"]
                    or source["amounts"]["total"] != row["original_amount"] or source["bindings"].get("project_id") != row["project_id"]
                    or source["bindings"].get("supplier_id") != row["supplier_id"]
                    or source["bindings"].get("retainage_rate") != row["retainage_rate"]
                    or project_scope is None or source.get("entity") != project_scope["entity"]
                    or source.get("currency") != project_scope["currency"]):
                _invalid_record()
            # Reverse each genuine change in memory. This verifies the current
            # SOV against every historical before-change source hash and the
            # initial execution, without mutating any business record.
            working = [{key: line[key] for key in ("id", "line_no", "description", "cost_code", "amount")} for line in row["sov"]]
            change_events = self.cipher.db.query("SELECT entity_id,payload_json FROM audit_log WHERE action='change.executed' AND json_extract(payload_json,'$.commitment_id')=? ORDER BY seq", (commitment_id,))
            changes = {change["id"]: change for change in row["changes"] if change["status"] == "executed"}
            if len(change_events) != len(changes) or {event["entity_id"] for event in change_events} != changes.keys():
                _invalid_record()
            if (executed.get("version") != 2 or row["version"] != 2 + len(change_events) + int(row["status"] == "closed")):
                _invalid_record()
            closure = self.cipher.commitments.closure(commitment_id)
            closed_events = self.cipher.db.query("SELECT actor,payload_json FROM audit_log WHERE action='commitment.closed' AND entity_type='commitment' AND entity_id=?", (commitment_id,))
            if row["status"] == "closed":
                if closure is None or len(closed_events) != 1:
                    _invalid_record()
                closed = loads(closed_events[0]["payload_json"])
                if (closure["commitment_version"] != row["version"] or closure["closed_at"] != row["closed_at"]
                        or closure["closed_by"] != closed_events[0]["actor"] or closed.get("version") != row["version"]
                        or closed.get("executed_amount") != row["executed_amount"]
                        or closed.get("basis") != closure["basis"] or closed.get("closeout_approval_id") != closure["closeout_approval_id"]):
                    _invalid_record()
            elif closure is not None or closed_events:
                _invalid_record()
            expected_amount = _money(row["original_amount"])
            for event in change_events:
                change = changes[event["entity_id"]]
                payload = loads(event["payload_json"])
                if payload.get("amount") != change["amount"] or payload.get("approval_id") != change["approval_id"]:
                    _invalid_record()
                expected_amount += _money(change["amount"])
            if expected_amount != _money(row["executed_amount"]) or _money(row["sov_total"]) != expected_amount:
                _invalid_record()
            for event in reversed(change_events):
                change = changes[event["entity_id"]]
                approved = self._consumed_source(change["approval_id"], "change.execute", "change", change["id"])
                bindings = approved["bindings"]
                if (approved["amounts"].get("change") != change["amount"] or bindings.get("commitment_id") != commitment_id
                        or bindings.get("sov_line_id") != change["sov_line_id"] or bindings.get("reason") != change["reason"]):
                    _invalid_record()
                if change["sov_line_id"]:
                    matching = [line for line in working if line["id"] == change["sov_line_id"]]
                    if len(matching) != 1:
                        _invalid_record()
                    matching[0]["amount"] = fmt(money(matching[0]["amount"]) - money(change["amount"]))
                else:
                    if not working:
                        _invalid_record()
                    added = max(working, key=lambda line: line["line_no"])
                    if added["description"] != "Change: " + change["reason"] or added["cost_code"] != "" or added["amount"] != change["amount"]:
                        _invalid_record()
                    working.remove(added)
                snapshot = [{key: line[key] for key in ("line_no", "description", "cost_code", "amount")}
                            for line in sorted(working, key=lambda line: line["line_no"])]
                if hash_json(snapshot) != bindings.get("sov_hash"):
                    _invalid_record()
            snapshot = [{key: line[key] for key in ("line_no", "description", "cost_code", "amount")}
                        for line in sorted(working, key=lambda line: line["line_no"])]
            if hash_json(snapshot) != source["bindings"].get("sov_hash"):
                _invalid_record()
            return row
        except APRefusal:
            raise
        except (ApprovalError, CommitmentError, ValueError, TypeError, KeyError):
            _invalid_record()

    def _bill(self, authority, bill_id: str) -> dict[str, Any]:
        row = self.cipher.db.one("SELECT b.id,c.project_id,p.currency FROM bills b JOIN commitments c ON c.id=b.commitment_id JOIN projects p ON p.id=c.project_id WHERE b.id=?", (bill_id,))
        if row is None or row["project_id"] not in authority.project_ids:
            _not_found()
        if row["currency"] != "USD":
            raise APRefusal(422, "unsupported_currency", "Practice displays support USD records only.", "currency")
        try:
            bill = self.cipher.bills.get(bill_id)
            self._commitment(bill["commitment_id"])
            self._verify_bill(bill)
            return bill
        except APRefusal:
            raise
        except (BillError, ValueError, TypeError, KeyError):
            _invalid_record()

    def _verify_bill(self, bill: dict[str, Any]) -> None:
        if any(not item["ok"] for item in self.cipher.bills.lifecycle_integrity_checks(bill["id"])):
            _invalid_record()
        # Certification is the source for an unposted economic display too. A
        # row-local hash alone does not establish that a bill was ever certified.
        events = self.cipher.db.query("SELECT payload_json FROM audit_log WHERE action='bill.certified' AND entity_type='bill' AND entity_id=?", (bill["id"],))
        if len(events) != 1:
            _invalid_record()
        payload = loads(events[0]["payload_json"])
        if (not isinstance(payload, dict) or any(payload.get(key) != bill[key] for key in
                ("commitment_id", "sequence", "amount_due", "retainage_this_period", "content_hash"))):
            _invalid_record()
        # The presenter never accepts a line total that contradicts its stored
        # bill header, even when an attacker removed SQLite storage triggers.
        installed = sum(_money(line["installed_this_period"]) for line in bill["lines"])
        cumulative = sum(_money(line["cumulative_installed"]) for line in bill["lines"])
        if installed != _money(bill["installed_this_period"]) or cumulative != _money(bill["cumulative_installed"]):
            _invalid_record()
        for line in bill["lines"]:
            if _money(line["cumulative_installed"]) - _money(line["prior_installed"]) != _money(line["installed_this_period"]):
                _invalid_record()
        sov = {line["id"]: line for line in self.cipher.db.query("SELECT id,line_no FROM sov_lines WHERE commitment_id=?", (bill["commitment_id"],))}
        if (len({line["sov_line_id"] for line in bill["lines"]}) != len(bill["lines"])
                or any(line["sov_line_id"] not in sov for line in bill["lines"])):
            _invalid_record()
        if bill.get("approval_record_id"):
            bound = loads(self.cipher.bills._business_record(bill)["snapshot_json"])["bindings"]
            if (bound.get("bill_immutable") != self.cipher.bills._immutable_bill_facts(bill)
                    or bound.get("bill_lines_hash") != hash_json(bill["lines"])
                    or bound.get("bill_transfers_hash") != hash_json(bill["transfers"])):
                _invalid_record()
        else:
            # Installed-work certification preserves enough fields to recompute
            # its entire original source hash. Original stored-lot quantities
            # are not all retained in the old certification audit payload; this
            # bounded presenter refuses that unsupported draft rather than
            # assert a complete reconstructed stored-material source proof.
            if (bill["transfers"] or payload.get("newly_billed_lots") or any(_money(bill[key]) for key in
                    ("cumulative_stored", "stored_added_this_period", "stored_transferred_this_period"))):
                raise APRefusal(422, "unsupported_presenter", "This practice workflow currently reviews installed-work bill sources.", "bill")
            content = {key: bill[key] for key in ("commitment_id", "commitment_version", "period_id", "sequence", "retainage_rate", "sov_hash",
                       "cumulative_installed", "cumulative_stored", "cumulative_gross", "cumulative_retainage", "cumulative_net", "prior_net", "amount_due")}
            content["lines"] = [{key: line[key] for key in ("sov_line_id", "cumulative_installed", "prior_installed", "installed_this_period")}
                                for line in sorted(bill["lines"], key=lambda item: sov[item["sov_line_id"]]["line_no"])]
            content.update(transfers=[], stored_lots=[], excluded_lots=payload.get("excluded_lots") or [])
            if hash_json(content) != bill["content_hash"]:
                _invalid_record()

    def _approval(self, authority, approval_id: str) -> dict[str, Any]:
        row = self.cipher.db.one("SELECT a.id,c.project_id FROM approvals a JOIN bills b ON a.subject_type='bill' AND b.id=a.subject_id JOIN commitments c ON c.id=b.commitment_id WHERE a.id=? AND a.operation='bill.approve'", (approval_id,))
        if row is None or row["project_id"] not in authority.project_ids:
            _not_found()
        try:
            approval = self.cipher.approvals.get(approval_id)
            bill = self._bill(authority, approval["subject_id"])
            manifest = approval["manifest"]
            if (not isinstance(manifest, dict) or manifest.get("operation") != "bill.approve"
                    or manifest.get("subject") != {"type": "bill", "id": bill["id"]}
                    or (manifest.get("bindings") or {}).get("project_id") != bill["project_id"]
                    or approval["manifest_hash"] != hash_json(manifest)
                    or approval["material_hash"] != material_hash(manifest)
                    or approval["nonce"] != manifest.get("nonce")
                    or approval["actor_role"] != manifest.get("actor_role")
                    or approval["policy_version"] != manifest.get("policy_version")):
                _invalid_record()
            expiry, original_expiry = parse_iso(approval["expires_at"]), parse_iso(manifest["expires_at"])
            if expiry.utcoffset() is None or original_expiry.utcoffset() is None or expiry > original_expiry:
                _invalid_record()
            events = self.cipher.db.query("SELECT action,actor,payload_json FROM audit_log WHERE entity_type='approval' AND entity_id=? ORDER BY seq", (approval_id,))
            requested = [event for event in events if event["action"] == "approval.requested"]
            if len(requested) != 1:
                _invalid_record()
            request = loads(requested[0]["payload_json"])
            if (request.get("manifest_hash") != approval["manifest_hash"] or request.get("operation") != "bill.approve"
                    or request.get("subject") != manifest["subject"] or requested[0]["actor"] != approval["requested_by"]):
                _invalid_record()
            granted = [event for event in events if event["action"] == "approval.granted"]
            terminal = [event for event in events if event["action"] in ("approval.expired", "approval.invalidated", "approval.consumed")]
            if approval["status"] in ("pending", "granted") and terminal:
                _invalid_record()
            if terminal and terminal[-1]["action"] != "approval." + approval["status"]:
                _invalid_record()
            if approval["status"] == "consumed" and any(event["action"] != "approval.consumed" for event in terminal):
                _invalid_record()
            if len(granted) > 1:
                _invalid_record()
            if approval["status"] == "pending" and (granted or approval["approver"] is not None):
                _invalid_record()
            if approval["status"] in ("granted", "consumed") and len(granted) != 1:
                _invalid_record()
            for event in granted:
                value = loads(event["payload_json"])
                if (event["actor"] != approval["approver"] or value.get("material_hash") != approval["material_hash"]
                        or value.get("operation") != "bill.approve"):
                    _invalid_record()
            if approval["status"] in ("expired", "invalidated", "consumed") and not any(
                    event["action"] == "approval." + approval["status"] for event in events):
                _invalid_record()
            return approval
        except APRefusal:
            raise
        except (ApprovalError, ValueError, TypeError, KeyError, OverflowError):
            _invalid_record()

    @_locked
    def require_resource(self, person_id: str, action: str, resource_id: str) -> dict[str, Any]:
        """Authorize current person/scope/duty without requiring a new lifecycle act.

        Receipt replay deliberately uses this before checking the original source
        proof. A later posted state does not revoke a currently authorized retry.
        """
        if action not in _ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported bill practice action.", "action")
        authority = self._authority(person_id)
        approval = action == "bill.approve"
        record = self._approval(authority, resource_id) if approval else self._bill(authority, resource_id)
        project_id = (record["manifest"].get("bindings") or {})["project_id"] if approval else record["project_id"]
        duty = "pm" if approval else "accountant"
        if not authority.allows(project_id, duty):
            raise APRefusal(403, "duty_required", "This practice action requires the corresponding duty on this project.", "duty")
        person = self.cipher.plugin("people").person_for(authority.login)
        return {"person": person, "personId": authority.person_id, "login": authority.login,
                "projectId": project_id, "duty": duty, "record": record, "authority": authority}

    def _sign(self, value: Any) -> str:
        return hmac.new(self.secret, canonical_json(value).encode("utf-8"), hashlib.sha256).hexdigest()

    def _version(self, authority, resource_id: str, *, approval: bool = False) -> str:
        record = self._approval(authority, resource_id) if approval else self._bill(authority, resource_id)
        bill = self._bill(authority, record["subject_id"]) if approval else record
        commitment = self._commitment(bill["commitment_id"])
        approval_rows = self.cipher.db.query("SELECT * FROM approvals WHERE operation='bill.approve' AND subject_type='bill' AND subject_id=? ORDER BY requested_at,id", (bill["id"],))
        # Current manifests contain an intentionally new nonce and expiry. They
        # are excluded; material/governance facts are the versioned proposal.
        current = None
        if bill["status"] in ("draft", "approved"):
            try:
                manifest = self.cipher._manifest("bill.approve", bill["id"], "pm")
                current = {"material": material_part(manifest), "governance": manifest.get("governance")}
            except (RuntimeError, ValueError, TypeError, KeyError):
                current = {"available": False}
        private = {"contractVersion": CONTRACT_VERSION, "workspace": self.cipher.db.mode_status(),
                   "personId": authority.person_id, "scope": authority.scope_hash, "approvalResource": approval,
                   "resource": record, "bill": bill, "commitment": commitment, "current": current,
                   "approvals": approval_rows,
                   "periods": self.cipher.db.query("SELECT id,name,start_date,end_date,status FROM periods ORDER BY start_date,id"),
                   "posting": self.cipher.bills.posting_receipt(bill["id"])}
        return "apv1-" + self._sign(private)

    @_locked
    def version(self, person_id: str, resource_id: str, *, approval: bool = False) -> str:
        return self._version(self._authority(person_id), resource_id, approval=approval)

    def _effective(self, approval: dict[str, Any], bill: dict[str, Any]) -> str:
        if approval["status"] not in ("pending", "granted"):
            return approval["status"]
        if parse_iso(approval["expires_at"]) <= utcnow():
            return "expired"
        if bill["status"] not in ("draft", "approved"):
            return "stale"
        try:
            current = self.cipher._manifest("bill.approve", bill["id"], "pm")
            if material_hash(current) != approval["material_hash"] or current.get("governance") != approval["manifest"].get("governance"):
                return "stale"
        except (RuntimeError, ValueError, TypeError, KeyError):
            return "stale"
        return approval["status"]

    def _review(self, authority, action: str, resource_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from .ap_preflight import APPreflight
        try:
            return APPreflight(self.cipher, self, secret=self.secret).review(authority.person_id, action, resource_id, body)
        except APRefusal as exc:
            if exc.status != 403:
                raise
            return {"allowed": False, "checks": [{"code": exc.code, "status": "blocked", "target": exc.target,
                                                   "message": exc.message, "fix": "Switch to the corresponding registered practice person."}]}

    def _bill_value(self, authority, bill: dict[str, Any]) -> BillRecord:
        commitment = self._commitment(bill["commitment_id"])
        project = self.cipher.db.one("SELECT name,currency FROM projects WHERE id=?", (bill["project_id"],))
        if project is None or project["currency"] != "USD":
            raise APRefusal(422, "unsupported_currency", "Practice displays support USD records only.", "currency")
        sov = {line["id"]: line for line in commitment["sov"]}
        lines = []
        for line in bill["lines"]:
            source = sov.get(line["sov_line_id"])
            if source is None:
                _invalid_record()
            lines.append({"id": line["id"], "sovLineId": line["sov_line_id"], "description": source["description"],
                          "costCode": source["cost_code"], "cumulativeInstalledCents": _money(line["cumulative_installed"]),
                          "priorInstalledCents": _money(line["prior_installed"]), "thisPeriodInstalledCents": _money(line["installed_this_period"])})
        approval = None
        if bill.get("business_approval_id"):
            approval = self._approval(authority, bill["business_approval_id"])
        else:
            latest = self.cipher.db.one("SELECT id FROM approvals WHERE operation='bill.approve' AND subject_type='bill' AND subject_id=? ORDER BY requested_at DESC,rowid DESC LIMIT 1", (bill["id"],))
            if latest:
                approval = self._approval(authority, latest["id"])
        business = None if approval is None else {
            "id": bill.get("approval_record_id"), "approvalId": approval["id"], "status": approval["status"],
            "effectiveStatus": self._effective(approval, bill), "requestedBy": self._person(approval["requested_by"]),
            "approvedBy": self._person(approval["approver"]), "requestedAt": approval["requested_at"],
            "approvedAt": approval["granted_at"], "expiresAt": approval["expires_at"]}
        receipt = self.cipher.bills.posting_receipt(bill["id"])
        posting = None if receipt is None else {
            "receiptId": receipt["id"], "journalIds": loads(receipt["journal_ids_json"]), "period": self._period(receipt["period_id"]),
            "postedBy": self._person(receipt["posted_by"]), "postedAt": receipt["posted_at"], "reason": receipt["reason"]}
        actions, blocked = [], []
        candidates = []
        if bill["status"] == "draft" and authority.allows(bill["project_id"], "accountant"):
            candidates.append(("bill.requestApproval", bill["id"], {}))
        if approval and approval["status"] == "pending" and authority.allows(bill["project_id"], "pm"):
            candidates.append(("bill.approve", approval["id"], {}))
        if bill["status"] == "approved" and authority.allows(bill["project_id"], "accountant"):
            candidates.append(("bill.post", bill["id"], {"periodId": bill["period_id"], "reason": ""}))
        for action, resource_id, body in candidates:
            review = self._review(authority, action, resource_id, body)
            if review["allowed"]:
                actions.append(action)
            else:
                blocked.extend({key: check.get(key) for key in ("code", "target", "message", "fix")}
                               for check in review["checks"] if check["status"] != "passed")
        effective_status = bill["status"]
        if bill["stale"] or business and business["effectiveStatus"] in ("stale", "expired", "invalidated") and bill["status"] in ("draft", "approved"):
            effective_status = business["effectiveStatus"] if business else "stale"
        period = self._period(bill["period_id"])
        posting_periods = [self._period(row["id"]) for row in self.cipher.db.query("SELECT id FROM periods WHERE status='open' AND start_date>=? ORDER BY start_date,id", (period["startDate"],))]
        return {"id": bill["id"], "version": self._version(authority, bill["id"]), "projectId": bill["project_id"],
                "commitmentId": bill["commitment_id"], "supplierId": bill["supplier_id"], "projectName": project["name"],
                "commitmentTitle": commitment["title"], "supplierName": commitment["supplier"]["name"], "sequence": bill["sequence"],
                "displayNumber": None, "status": bill["status"], "effectiveStatus": effective_status, "certificationPeriod": period,
                "amountDueCents": _money(bill["amount_due"]), "currentDueCents": _money(self.cipher.bills.open_payable(bill["id"])),
                "retainageCents": _money(bill["retainage_this_period"]),
                "thisPeriodCents": _money(bill["installed_this_period"]) + _money(bill["stored_added_this_period"]) - _money(bill["stored_transferred_this_period"]),
                "lines": lines, "businessApproval": business, "posting": posting, "postingPeriods": posting_periods,
                "availableActions": actions, "blockedReasons": blocked}

    @_locked
    def detail(self, person_id: str, bill_id: str) -> dict[str, Any]:
        authority = self._authority(person_id)
        return {**PROVENANCE, **self._bill_value(authority, self._bill(authority, bill_id))}

    def _approval_value(self, authority, approval: dict[str, Any]) -> dict[str, Any]:
        bill = self._bill(authority, approval["subject_id"])
        project = self.cipher.db.one("SELECT name,currency FROM projects WHERE id=?", (bill["project_id"],))
        if project["currency"] != "USD":
            raise APRefusal(422, "unsupported_currency", "Practice displays support USD records only.", "currency")
        return {"id": approval["id"], "version": self._version(authority, approval["id"], approval=True), "billId": bill["id"],
                "projectId": bill["project_id"], "projectName": project["name"], "subjectLabel": f"Bill {bill['sequence']}",
                "status": approval["status"], "effectiveStatus": self._effective(approval, bill),
                "requestedBy": self._person(approval["requested_by"]), "approvedBy": self._person(approval["approver"]),
                "requestedAt": approval["requested_at"], "approvedAt": approval["granted_at"], "expiresAt": approval["expires_at"],
                "amountDueCents": _money(approval["manifest"]["amounts"]["amount_due"])}

    @staticmethod
    def _facts(manifest: dict[str, Any]) -> dict[str, Any]:
        bindings, amounts = manifest.get("bindings") or {}, manifest.get("amounts") or {}
        invoice = bindings.get("supplier_invoice")
        return {"amountDueCents": _money(amounts["amount_due"]), "retainageCents": _money(amounts["retainage_this_period"]),
                "cumulativeGrossCents": _money(amounts["cumulative_gross"]), "commitmentVersion": bindings.get("commitment_version"),
                "certificationPeriodId": bindings.get("period_id"), "sequence": bindings.get("sequence"),
                "supplierName": (bindings.get("supplier_identity") or {}).get("name"),
                "supplierInvoiceAttached": invoice is not None, "storedEvidenceCount": len(bindings.get("stored_lots") or [])}

    @_locked
    def packet(self, person_id: str, approval_id: str) -> dict[str, Any]:
        authority = self._authority(person_id)
        approval = self._approval(authority, approval_id)
        bill = self._bill(authority, approval["subject_id"])
        bound = self._facts(approval["manifest"])
        try:
            current_manifest = self.cipher._manifest("bill.approve", bill["id"], "pm")
            current = self._facts(current_manifest)
        except (RuntimeError, ValueError, TypeError, KeyError):
            current = {"available": False, "message": "Current business facts require a fresh review."}
        changes = [{"field": key, "before": bound.get(key), "after": current.get(key)}
                   for key in sorted(bound.keys() | current.keys()) if bound.get(key) != current.get(key)]
        review = self._review(authority, "bill.approve", approval_id, {})
        row = self._approval_value(authority, approval)
        return {**PROVENANCE, "approvalId": approval_id, "billId": bill["id"], "version": row["version"],
                "status": row["status"], "effectiveStatus": row["effectiveStatus"], "requestedBy": row["requestedBy"],
                "approvedBy": row["approvedBy"], "requestedAt": row["requestedAt"], "expiresAt": row["expiresAt"],
                "boundFacts": bound, "currentFacts": current, "changes": changes, "checks": review["checks"],
                "amountDueCents": bound["amountDueCents"], "retainedCents": bound["retainageCents"],
                "sourceSummary": {"supplierName": bound["supplierName"], "certificationPeriod": self._period(bill["period_id"]),
                                  "supplierInvoiceAttached": bound["supplierInvoiceAttached"], "storedEvidenceCount": bound["storedEvidenceCount"]},
                "effect": {"billStatus": "approved", "workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0},
                "bill": self._bill_value(authority, bill)}

    def _token(self, payload: dict[str, Any]) -> str:
        data = base64.urlsafe_b64encode(canonical_json(payload).encode()).decode().rstrip("=")
        return data + "." + hmac.new(self.secret, data.encode(), hashlib.sha256).hexdigest()

    def _cursor_key(self, cursor: str | None, binding: str) -> tuple[str, str] | None:
        if cursor is None:
            return None
        try:
            data, signature = cursor.split(".")
            expected = hmac.new(self.secret, data.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True))
            if (not isinstance(payload, dict) or set(payload) != {"v", "binding", "last"} or payload["v"] != 1
                    or payload["binding"] != binding or not isinstance(payload["last"], list) or len(payload["last"]) != 2
                    or any(not isinstance(value, str) or not value or len(value) > 200 for value in payload["last"])):
                raise ValueError
            return tuple(payload["last"])
        except (ValueError, TypeError, UnicodeError, binascii.Error):
            raise APRefusal(422, "invalid_cursor", "The cursor does not match this person's current practice query.", "cursor") from None

    def _envelope(self, authority, collection: str, pairs: list[tuple[tuple[str, str], dict[str, Any]]], *,
                  project_id: str | None, status: str | None, search: str | None, top: int, cursor: str | None,
                  ready: bool | None = None) -> dict[str, Any]:
        binding = self._sign({"version": CONTRACT_VERSION, "collection": collection, "person": authority.person_id,
                              "scope": authority.scope_hash, "project": project_id, "status": status,
                              "search": search, "top": top, "ready": ready, "sort": "createdAt,id"})
        last = self._cursor_key(cursor, binding)
        pairs.sort(key=lambda pair: pair[0])
        if status is not None:
            pairs = [pair for pair in pairs if pair[1]["status"] == status]
        if ready is not None:
            pairs = [pair for pair in pairs if pair[1]["ready"] == ready]
        if search:
            fields = ("name", "entity", "customerName", "title", "supplierName", "projectName", "commitmentTitle", "subjectLabel")
            pairs = [pair for pair in pairs if any(search in str(pair[1].get(key) or "").casefold() for key in fields)
                     or search in f"bill {pair[1].get('sequence', '')}".casefold()]
        values = [pair[1] for pair in pairs]
        count = len(values)
        selected = [pair for pair in pairs if last is None or pair[0] > last]
        page = selected[:top]
        next_cursor = self._token({"v": 1, "binding": binding, "last": list(page[-1][0])}) if len(selected) > top else None
        statuses = {}
        for row in values:
            if "status" in row:
                statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        try:
            totals = _totals("bills" if collection == "posting-queue" else collection, values)
        except PracticeReadRefusal as exc:
            raise APRefusal(422, exc.code, exc.message, exc.target) from None
        return {**PROVENANCE, "collection": collection, "projectId": project_id, "value": [pair[1] for pair in page],
                "count": count, "nextCursor": next_cursor, "facets": {"statuses": [{"value": key, "count": value} for key, value in sorted(statuses.items())]},
                "totals": totals}

    def _validate_query(self, collection, project_id, status, search, top, cursor):
        try:
            return _validate(collection, project_id, status, search, top, cursor)
        except PracticeReadRefusal as exc:
            raise APRefusal(422, exc.code, exc.message, exc.target) from None

    @_locked
    def read(self, person_id: str, collection: str, *, project_id: str | None = None, status: str | None = None,
             search: str | None = None, top: int = 50, cursor: str | None = None) -> dict[str, Any]:
        search = self._validate_query(collection, project_id, status, search, top, cursor)
        authority = self._authority(person_id)
        if project_id is not None and project_id not in authority.project_ids:
            _not_found()
        project_ids = (project_id,) if project_id else authority.project_ids
        pairs = []
        for project in project_ids:
            if self.cipher.db.scalar("SELECT currency FROM projects WHERE id=?", (project,)) != "USD":
                raise APRefusal(422, "unsupported_currency", "Practice displays support USD records only.", "currency")
            if collection == "projects":
                row = self.cipher.db.one("SELECT p.id,p.name,p.entity,p.currency,p.budget,p.created_at,c.name AS customer_name FROM projects p LEFT JOIN parties c ON c.id=p.customer_id WHERE p.id=?", (project,))
                if row["currency"] != "USD":
                    raise APRefusal(422, "unsupported_currency", "Practice displays support USD records only.", "currency")
                value = {"id": row["id"], "name": row["name"], "entity": row["entity"], "currency": "USD", "displayNumber": None,
                         "customerName": row["customer_name"], "budgetCents": _money(row["budget"])}
                pairs.append(((row["created_at"], row["id"]), value))
            elif collection == "commitments":
                for item in self.cipher.db.query("SELECT id FROM commitments WHERE project_id=? ORDER BY created_at,id", (project,)):
                    row = self._commitment(item["id"])
                    value = {"id": row["id"], "projectId": project, "projectName": self.cipher.db.scalar("SELECT name FROM projects WHERE id=?", (project,)),
                             "supplierId": row["supplier_id"], "supplierName": row["supplier"]["name"], "title": row["title"], "displayNumber": None,
                             "status": row["status"], "version": row["version"], "originalAmountCents": _money(row["original_amount"]),
                             "executedAmountCents": _money(row["executed_amount"]), "retainageRateMicros": int(rate(row["retainage_rate"]) * 1_000_000)}
                    pairs.append(((row["created_at"], row["id"]), value))
            elif collection == "bills":
                for row in self.cipher.db.query("SELECT b.id,b.created_at FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE c.project_id=?", (project,)):
                    pairs.append(((row["created_at"], row["id"]), self._bill_value(authority, self._bill(authority, row["id"]))))
            else:
                for row in self.cipher.db.query("SELECT a.id,a.requested_at FROM approvals a JOIN bills b ON a.subject_type='bill' AND b.id=a.subject_id JOIN commitments c ON c.id=b.commitment_id WHERE a.operation='bill.approve' AND c.project_id=?", (project,)):
                    pairs.append(((row["requested_at"], row["id"]), self._approval_value(authority, self._approval(authority, row["id"]))))
        return self._envelope(authority, collection, pairs, project_id=project_id, status=status, search=search, top=top, cursor=cursor)

    @_locked
    def posting_queue(self, person_id: str, *, project_id: str | None = None, ready: bool | None = None,
                      top: int = 50, cursor: str | None = None) -> dict[str, Any]:
        self._validate_query("bills", project_id, None, None, top, cursor)
        if ready is not None and type(ready) is not bool:
            raise APRefusal(422, "invalid_query", "Choose a Boolean posting readiness filter.", "ready")
        authority = self._authority(person_id)
        if project_id is not None and project_id not in authority.project_ids:
            _not_found()
        pairs = []
        for project in ((project_id,) if project_id else authority.project_ids):
            for row in self.cipher.db.query("SELECT b.id,b.created_at FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE c.project_id=? AND b.status='approved'", (project,)):
                bill = self._bill(authority, row["id"])
                value = self._bill_value(authority, bill)
                business = value["businessApproval"]
                review = self._review(authority, "bill.post", bill["id"], {"periodId": bill["period_id"], "reason": ""})
                queue = {"billId": bill["id"], "version": value["version"], "projectId": project, "supplierName": value["supplierName"],
                         "commitmentTitle": value["commitmentTitle"], "sequence": value["sequence"], "status": bill["status"],
                         "amountDueCents": value["amountDueCents"], "currentDueCents": value["currentDueCents"],
                         "certificationPeriod": value["certificationPeriod"], "businessApprovalId": business["approvalId"],
                         "approvedBy": business["approvedBy"], "approvedAt": business["approvedAt"], "expiresAt": business["expiresAt"],
                         "ready": review["allowed"], "blockedReasons": [{key: check.get(key) for key in ("code", "target", "message", "fix")}
                                                                      for check in review["checks"] if check["status"] != "passed"]}
                pairs.append(((row["created_at"], row["id"]), queue))
        return self._envelope(authority, "posting-queue", pairs, project_id=project_id, status=None, search=None, top=top, cursor=cursor, ready=ready)
