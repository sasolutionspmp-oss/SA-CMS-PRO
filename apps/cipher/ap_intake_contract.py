"""Scoped source-backed reads for installed-work invoice intake and matching.

This extends the disposable AP entry only. Private source facts are signed into
versions but never returned to the browser. Every displayed record is scoped
before its evidence, bill, supplier, counts or money is inspected.
"""
from __future__ import annotations

import hashlib
import hmac
from functools import wraps
from typing import Any

from .ap_contract import APContract, APRefusal, PROVENANCE, _invalid_record, _money, _not_found
from .api_contract import MAX_SAFE_INTEGER
from .core.approvals import material_hash, material_part
from .core.ids import canonical_json, hash_json, loads, parse_iso, utcnow
from .core.money import rate

MATCH_OPERATION = "ap_intake.match_invoice"
ACTIONS = frozenset(("bill.prepare", "invoice.receive", "invoice.computeMatch", "invoice.requestMatchApproval",
                     "invoice.approveMatch", "invoice.executeMatch"))
RESOURCE_TYPES = {"bill.prepare": "commitment", "invoice.receive": "commitment", "invoice.computeMatch": "invoice",
                  "invoice.requestMatchApproval": "invoice", "invoice.approveMatch": "approval", "invoice.executeMatch": "approval"}
STATUSES = {"invoices": ("received", "matched", "rejected"), "invoice-evidence": ("available", "in_use"),
            "match-approvals": ("pending", "granted", "consumed", "expired", "invalidated")}
EXCEPTIONS = {
    "amount_mismatch": "The invoice amount does not equal the eligible certified bill.",
    "not_received": "The required purchased items have not been received.",
    "damaged_receipt": "A required receipt reports damaged goods.",
    "no_certified_bill": "Prepare an eligible bill for this subcontract before requesting a match approval.",
    "possible_duplicate": "A possible duplicate requires a separate documented review.",
    "evidence_stale": "The invoice evidence has a newer revision; review the invoice source.",
    "over_commitment": "The invoice would exceed the authorized subcontract or previously matched amount.",
}


def _locked(method):
    """Hold a consistent scoped read and translate untrusted source failures."""
    @wraps(method)
    def read(self, *args, **kwargs):
        with self.cipher.db._lock:
            try:
                return method(self, *args, **kwargs)
            except APRefusal:
                raise
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
                _invalid_record()
    return read


class APIntakeContract:
    def __init__(self, cipher, base: APContract, *, secret: bytes):
        if base.cipher is not cipher or not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("Intake contract requires its owned AP workspace and a server signing key.")
        self.cipher, self.base, self.secret = cipher, base, secret
        self.ap = cipher.plugin("ap_intake")

    def _sign(self, value):
        return hmac.new(self.secret, canonical_json(value).encode(), hashlib.sha256).hexdigest()

    def _project(self, authority, project_id):
        if project_id not in authority.project_ids:
            _not_found()
        row = self.cipher.db.one("SELECT id,name,currency FROM projects WHERE id=?", (project_id,))
        if row is None:
            _not_found()
        if row["currency"] != "USD":
            raise APRefusal(422, "unsupported_currency", "Practice displays support USD records only.", "currency")
        return row

    def _commitment(self, authority, commitment_id):
        scope = self.cipher.db.one("SELECT project_id FROM commitments WHERE id=?", (commitment_id,))
        if scope is None:
            _not_found()
        self._project(authority, scope["project_id"])
        return self.base._commitment(commitment_id)

    def _evidence(self, authority, revision_id):
        row = self.cipher.db.one("SELECT r.*,d.project_id,d.kind,d.title FROM document_revisions r JOIN documents d ON d.id=r.document_id WHERE r.id=?", (revision_id,))
        if row is None:
            _not_found()
        self._project(authority, row["project_id"])
        if row["kind"] != "supplier_invoice":
            raise APRefusal(422, "unsupported_evidence", "Choose a supplier invoice evidence revision.", "evidenceRevisionId")
        registrations = self.cipher.db.query("SELECT payload_json FROM audit_log WHERE action='document.registered' AND entity_type='document' AND entity_id=?", (row["document_id"],))
        if len(registrations) != 1 or loads(registrations[0]["payload_json"]) != {
                "project_id": row["project_id"], "kind": row["kind"], "title": row["title"]}:
            _invalid_record()
        revisions = self.cipher.db.query("SELECT * FROM document_revisions WHERE document_id=? ORDER BY revision", (row["document_id"],))
        events = self.cipher.db.query("SELECT payload_json FROM audit_log WHERE action='document.revised' AND entity_type='document' AND entity_id=? ORDER BY seq", (row["document_id"],))
        if len(revisions) != len(events) or not revisions:
            _invalid_record()
        for number, (revision, event) in enumerate(zip(revisions, events), 1):
            if revision["revision"] != number or loads(event["payload_json"]) != {
                    "revision_id": revision["id"], "revision": number, "content_hash": revision["content_hash"], "note": revision["note"]}:
                _invalid_record()
        return {**row, "is_current": row["id"] == revisions[-1]["id"]}

    def evidence(self, person_id, revision_id):
        """Internal scoped source lookup; HTTP exposes only the evidence presenter."""
        with self.cipher.db._lock:
            authority = self.base._authority(person_id)
            evidence = self._evidence(authority, revision_id)
            self._evidence_available(authority, evidence["document_id"])
            return evidence

    def _evidence_available(self, authority, document_id):
        """A source is reusable only after an audited final rejection released it."""
        self.ap.require_invoice_source_integrity(evidence_document_id=document_id)
        rows = self.cipher.db.query("SELECT id FROM ap_invoices WHERE evidence_document_id=? ORDER BY id", (document_id,))
        return all(self._invoice(authority, row["id"])["status"] == "rejected" for row in rows)

    def _attempts(self, inv):
        rows = self.cipher.db.query("SELECT * FROM ap_invoice_matches WHERE invoice_id=? ORDER BY computed_at,id", (inv["id"],))
        events = self.cipher.db.query("SELECT * FROM audit_log WHERE action='ap_intake.match_computed' AND entity_type='ap_invoice' AND entity_id=? ORDER BY seq", (inv["id"],))
        by_id = {loads(event["payload_json"]).get("attempt_id"): event for event in events}
        if len(by_id) != len(events) or set(by_id) != {row["id"] for row in rows}:
            _invalid_record()
        for row in rows:
            event = by_id[row["id"]]
            facts, payload = loads(row["result_json"]), loads(event["payload_json"])
            if (row["result_json"] != canonical_json(facts) or row["result_hash"] != hash_json(facts)
                    or facts["invoice"]["id"] != inv["id"] or facts["invoice"]["version"] != row["invoice_version"]
                    or row["status"] != facts["status"] or row["basis"] != facts["basis"]
                    or row["exceptions_json"] != canonical_json(facts["exceptions"])
                    or event["actor"] != row["computed_by"]
                    or any(payload.get(key) != row[key] for key in ("invoice_version", "basis", "status", "result_hash"))
                    or payload.get("exceptions") != facts["exceptions"]
                    or payload.get("bill_id") != (facts["bill"] or {}).get("id")
                    or payload.get("receipts") != [r["receipt_id"] for r in facts["receipts"]]):
                _invalid_record()
        return rows

    def _lifecycle(self, row, history, attempts):
        """Replay immutable invoice transitions rather than trust the current status."""
        state, version, source, last_match = None, 0, None, None
        by_id = {attempt["id"]: attempt for attempt in attempts}
        for event in history:
            action, payload = event["action"], loads(event["payload_json"])
            if action == "ap_intake.invoice_received":
                if state is not None:
                    _invalid_record()
                state, version, source = "received", 1, payload
            elif action == "ap_intake.invoice_revised":
                if (state not in ("received", "matched") or payload.get("previous_status") != state
                        or payload.get("version") != version + 1):
                    _invalid_record()
                state, version, source = "received", version + 1, payload
            elif action == "ap_intake.match_reopened":
                if (state != "matched" or last_match is None or payload.get("version") != version + 1
                        or payload.get("previous_approval_id") != last_match["approval_id"]
                        or payload.get("bill_id") != last_match["bill_id"]
                        or payload.get("commitment_id") != last_match["commitment_id"]):
                    _invalid_record()
                state, version, source = "received", version + 1, payload
            elif action == "ap_intake.invoice_matched":
                if state != "received" or payload.get("invoice_version") != version:
                    _invalid_record()
                approval_id = payload.get("approval_id")
                self.ap.approval_proof(approval_id)
                manifest = self.base._consumed_source(approval_id, MATCH_OPERATION, "ap_invoice", row["id"])
                approval = self.cipher.approvals.get(approval_id)
                bound = manifest["bindings"]
                attempt = by_id.get(payload.get("attempt_id"))
                if attempt is None:
                    _invalid_record()
                facts = loads(attempt["result_json"])
                if (approval["consumed_by"] != event["actor"] or bound.get("invoice_version") != version
                        or bound.get("invoice_hash") != source["content_hash"]
                        or bound.get("match_attempt_id") != attempt["id"] or bound.get("result_hash") != attempt["result_hash"]
                        or attempt["invoice_version"] != version or attempt["status"] != "matched"
                        or facts["invoice"]["content_hash"] != source["content_hash"]
                        or payload.get("amount") != source["amount"] or manifest["amounts"].get("invoice_amount") != source["amount"]
                        or payload.get("bill_id") != (bound.get("bill") or {}).get("id")
                        or payload.get("bill_id") != (facts.get("bill") or {}).get("id")
                        or payload.get("commitment_id") != (bound.get("commitment") or {}).get("id")
                        or payload.get("commitment_id") != (facts.get("commitment") or {}).get("id")
                        or bound.get("project_id") != row["project_id"] or bound.get("supplier_id") != row["supplier_id"]):
                    _invalid_record()
                state, last_match = "matched", payload
            elif action == "ap_intake.invoice_rejected":
                if state != "received" or payload.get("version") != version:
                    _invalid_record()
                state = "rejected"
        if state != row["status"] or version != row["version"]:
            _invalid_record()

    def _invoice(self, authority, invoice_id):
        row = self.cipher.db.one("SELECT * FROM ap_invoices WHERE id=?", (invoice_id,))
        if row is None:
            _not_found()
        self._project(authority, row["project_id"])
        try:
            # The same domain proof protects computation, aggregate controls,
            # exact retries and this presenter; display checks add scoped
            # document/commitment references and historical packet detail.
            self.ap.invoice_proof(invoice_id)
            if row["commitment_id"]:
                commitment = self._commitment(authority, row["commitment_id"])
                if commitment["project_id"] != row["project_id"] or commitment["supplier_id"] != row["supplier_id"]:
                    _invalid_record()
            if self.ap._integrity_problem(row):
                _invalid_record()
            history = self.cipher.db.query("SELECT * FROM audit_log WHERE entity_type='ap_invoice' AND entity_id=? ORDER BY seq", (invoice_id,))
            born = [event for event in history if event["action"] == "ap_intake.invoice_received"]
            if len(born) != 1:
                _invalid_record()
            origin = loads(born[0]["payload_json"])
            if (born[0]["actor"] != row["created_by"] or origin.get("project_id") != row["project_id"]
                    or origin.get("supplier_id") != row["supplier_id"]):
                _invalid_record()
            versions = [event for event in history if event["action"] in ("ap_intake.invoice_revised", "ap_intake.match_reopened")]
            if row["version"] != len(versions) + 1 or any(loads(event["payload_json"]).get("version") != version
                                                        for version, event in enumerate(versions, 2)):
                _invalid_record()
            source = loads(versions[-1]["payload_json"]) if versions else origin
            if (source.get("content_hash") != row["content_hash"] or source.get("amount") != row["amount"]
                    or source.get("possible_duplicate") != row["possible_duplicate"]):
                _invalid_record()
            duplicate_source = next((loads(event["payload_json"]) for event in reversed([*born, *versions])
                                     if "possible_duplicate_of" in loads(event["payload_json"])), origin)
            if canonical_json(duplicate_source.get("possible_duplicate_of", [])) != row["duplicate_of_json"]:
                _invalid_record()
            if not versions and any(origin.get(key) != row[key] for key in (
                    "commitment_id", "invoice_number", "number_key", "invoice_date", "due_date", "terms_days", "evidence_hash", "evidence_revision_id")):
                _invalid_record()
            evidence = self._evidence(authority, row["evidence_revision_id"])
            if (evidence["project_id"] != row["project_id"] or evidence["document_id"] != row["evidence_document_id"]
                    or evidence["content_hash"] != row["evidence_hash"]):
                _invalid_record()
            reviews = [event for event in history if event["action"] == "ap_intake.duplicate_flag_cleared"
                       and loads(event["payload_json"]).get("version") == row["version"]]
            if row["duplicate_cleared_at"] is None:
                if reviews or row["duplicate_cleared_by"] is not None or row["duplicate_clear_reason"] is not None:
                    _invalid_record()
            else:
                # A review can survive a revision that did not change duplicate facts.
                candidates = [event for event in history if event["action"] == "ap_intake.duplicate_flag_cleared"]
                if not candidates:
                    _invalid_record()
                review = candidates[-1]
                payload = loads(review["payload_json"])
                if (review["actor"] != row["duplicate_cleared_by"] or payload.get("cleared_by") != row["duplicate_cleared_by"]
                        or payload.get("cleared_at") != row["duplicate_cleared_at"] or payload.get("reason") != row["duplicate_clear_reason"]
                        or canonical_json(payload.get("possible_duplicate_of")) != row["duplicate_of_json"]):
                    _invalid_record()
            attempts = self._attempts(row)
            self._lifecycle(row, history, attempts)
            matches = [event for event in history if event["action"] == "ap_intake.invoice_matched"]
            if matches:
                last_match = matches[-1]
                proof = loads(last_match["payload_json"])
                if (proof.get("approval_id") != row["match_approval_id"] or proof.get("bill_id") != row["matched_bill_id"]
                        or proof.get("commitment_id") != row["matched_commitment_id"] or last_match["actor"] != row["matched_by"]
                        or row["matched_at"] is None or parse_iso(row["matched_at"]).utcoffset() is None):
                    _invalid_record()
            elif any(row[key] is not None for key in ("match_approval_id", "matched_bill_id", "matched_commitment_id", "matched_by", "matched_at")):
                _invalid_record()
            current = next((attempt for attempt in attempts if attempt["id"] == row["match_attempt_id"]), None)
            if row["match_attempt_id"] is None:
                if row["match_status"] is not None or row["match_basis"] is not None or row["match_exceptions_json"] != "[]":
                    _invalid_record()
            elif (current is None or current["invoice_version"] != row["version"] or current["status"] != row["match_status"]
                  or current["basis"] != row["match_basis"] or current["exceptions_json"] != row["match_exceptions_json"]):
                _invalid_record()
            if row["status"] == "matched":
                manifest = self.base._consumed_source(row["match_approval_id"], MATCH_OPERATION, "ap_invoice", invoice_id)
                matched = [event for event in history if event["action"] == "ap_intake.invoice_matched"
                           and loads(event["payload_json"]).get("approval_id") == row["match_approval_id"]]
                if len(matched) != 1:
                    _invalid_record()
                match = loads(matched[0]["payload_json"])
                if (matched[0]["actor"] != row["matched_by"] or match.get("invoice_version") != row["version"]
                        or match.get("attempt_id") != row["match_attempt_id"] or match.get("bill_id") != row["matched_bill_id"]
                        or match.get("amount") != row["amount"] or manifest["bindings"].get("invoice_hash") != row["content_hash"]
                        or manifest["bindings"].get("result_hash") != current["result_hash"]
                        or row["matched_commitment_id"] != (manifest["bindings"].get("commitment") or {}).get("id")
                        or row["matched_commitment_id"] != (loads(current["result_json"]).get("commitment") or {}).get("id")):
                    _invalid_record()
            elif row["status"] == "rejected":
                rejected = [event for event in history if event["action"] == "ap_intake.invoice_rejected"]
                if (len(rejected) != 1 or rejected[0]["actor"] != row["rejected_by"]
                        or loads(rejected[0]["payload_json"]).get("reason") != row["reject_reason"]
                        or loads(rejected[0]["payload_json"]).get("rejected_at") != row["rejected_at"]):
                    _invalid_record()
            elif row["status"] != "received":
                _invalid_record()
            return row
        except APRefusal:
            raise
        except (RuntimeError, ValueError, TypeError, KeyError):
            _invalid_record()

    def _approval(self, authority, approval_id):
        row = self.cipher.db.one("SELECT a.id,i.project_id FROM approvals a JOIN ap_invoices i ON a.subject_id=i.id AND a.subject_type='ap_invoice' WHERE a.id=? AND a.operation=?", (approval_id, MATCH_OPERATION))
        if row is None:
            _not_found()
        self._project(authority, row["project_id"])
        approval = self.cipher.approvals.get(approval_id)
        self.ap.approval_proof(approval_id)
        self._invoice(authority, approval["subject_id"])
        manifest = approval["manifest"]
        if (manifest.get("operation") != MATCH_OPERATION or manifest.get("subject") != {"type": "ap_invoice", "id": approval["subject_id"]}
                or manifest.get("actor_role") != "accountant" or approval["actor_role"] != "accountant"
                or manifest["bindings"].get("project_id") != row["project_id"]
                or approval["manifest_hash"] != hash_json(manifest) or approval["material_hash"] != material_hash(manifest)
                or approval["nonce"] != manifest.get("nonce") or approval["policy_version"] != manifest.get("policy_version")):
            _invalid_record()
        return approval

    @_locked
    def authorize(self, person_id, action, resource_id):
        if action not in ACTIONS:
            raise APRefusal(422, "unsupported_action", "Choose a supported invoice practice action.", "action")
        authority = self.base._authority(person_id)
        resource_type = RESOURCE_TYPES[action]
        record = self._commitment(authority, resource_id) if resource_type == "commitment" else self._invoice(authority, resource_id) if resource_type == "invoice" else self._approval(authority, resource_id)
        project_id = record["manifest"]["bindings"]["project_id"] if resource_type == "approval" else record["project_id"]
        if not authority.allows(project_id, "accountant"):
            raise APRefusal(403, "duty_required", "This practice action requires the accountant duty on this project.", "duty")
        return {"person": self.cipher.plugin("people").person_for(authority.login), "personId": authority.person_id,
                "login": authority.login, "projectId": project_id, "duty": "accountant", "record": record, "authority": authority}

    def _version(self, authority, resource_id, resource_type):
        if resource_type not in ("commitment", "invoice", "approval"):
            raise APRefusal(422, "unsupported_resource", "Choose a supported invoice record.", "record")
        record = self._commitment(authority, resource_id) if resource_type == "commitment" else self._invoice(authority, resource_id) if resource_type == "invoice" else self._approval(authority, resource_id)
        invoice = self._invoice(authority, record["subject_id"]) if resource_type == "approval" else record if resource_type == "invoice" else None
        commitment = record if resource_type == "commitment" else self._commitment(authority, invoice["commitment_id"]) if invoice["commitment_id"] else None
        project_id = commitment["project_id"] if commitment else invoice["project_id"]
        supplier_id = commitment["supplier_id"] if commitment else invoice["supplier_id"]
        current = None
        if invoice:
            try:
                manifest = self.cipher._manifest(MATCH_OPERATION, invoice["id"], "accountant")
                current = {"material": material_part(manifest), "governance": manifest.get("governance")}
            except (RuntimeError, ValueError, TypeError, KeyError):
                current = {"available": False}
        private = {"provenance": PROVENANCE, "workspace": self.cipher.db.mode_status(), "person": authority.person_id,
                   "scope": authority.scope_hash, "resourceType": resource_type, "record": record, "commitment": commitment,
                   "current": current, "terms": self.ap.audited_terms(supplier_id),
                   "periods": self.cipher.db.query("SELECT * FROM periods ORDER BY start_date,id"),
                   "documents": self.cipher.db.query("SELECT d.*,r.id AS revision_id,r.content_hash,r.revision FROM documents d JOIN document_revisions r ON r.document_id=d.id WHERE d.project_id=? AND d.kind='supplier_invoice' ORDER BY d.id,r.revision", (project_id,)),
                   "duplicatePool": self.cipher.db.query("SELECT * FROM ap_invoices WHERE supplier_id=? ORDER BY id", (supplier_id,)),
                   "bills": self.cipher.bills.list(commitment_id=commitment["id"]) if commitment else [],
                   "lots": self.cipher.bills.lots(commitment["id"]) if commitment else [],
                   "approvals": self.cipher.db.query("SELECT * FROM approvals WHERE operation=? AND subject_type='ap_invoice' AND subject_id=? ORDER BY requested_at,id", (MATCH_OPERATION, invoice["id"])) if invoice else []}
        return "api1-" + self._sign(private)

    @_locked
    def version(self, person_id, resource_id, resource_type):
        return self._version(self.base._authority(person_id), resource_id, resource_type)

    def _preparation(self, authority, commitment_id):
        commitment = self._commitment(authority, commitment_id)
        prior = self.cipher.bills.latest(commitment_id)
        if prior:
            prior = self.base._bill(authority, prior["id"])
        prior_lines = {line["sov_line_id"]: line for line in prior["lines"]} if prior else {}
        blocks = []
        if commitment["status"] != "executed":
            blocks.append({"code": "commitment_not_executed", "message": "Bill preparation requires an executed subcontract.", "target": "commitment"})
        if prior and prior["status"] == "draft":
            blocks.append({"code": "draft_predecessor", "message": "Complete or cancel the current draft before preparing its successor.", "target": "bill"})
        has_stored = any(not lot["withdrawn"] for lot in self.cipher.bills.lots(commitment_id))
        is_purchase_order = self.cipher.db.one("SELECT id FROM procurement_awards WHERE commitment_id=?", (commitment_id,)) is not None
        if has_stored:
            blocks.append({"code": "unsupported_stored_material", "message": "This preparation form currently supports installed work without stored materials.", "target": "commitment"})
        if is_purchase_order:
            blocks.append({"code": "unsupported_purchase_order", "message": "This practice preparation and intake form currently supports progress subcontracts.", "target": "commitment"})
        accounting = authority.allows(commitment["project_id"], "accountant")
        if not accounting:
            blocks.append({"code": "duty_required", "message": "The accountant duty is required to prepare this bill or receive an invoice.", "target": "duty"})
        return {**PROVENANCE, "id": commitment_id, "version": self._version(authority, commitment_id, "commitment"),
                "projectId": commitment["project_id"], "projectName": self._project(authority, commitment["project_id"])["name"],
                "commitmentTitle": commitment["title"], "supplierId": commitment["supplier_id"], "supplierName": commitment["supplier"]["name"],
                "status": commitment["status"], "retainageRateMicros": int(rate(commitment["retainage_rate"]) * 1_000_000),
                "lines": [{"sovLineId": line["id"], "lineNo": line["line_no"], "description": line["description"], "costCode": line["cost_code"],
                           "scheduledCents": _money(line["amount"]), "priorInstalledCents": _money(prior_lines.get(line["id"], {}).get("cumulative_installed", "0.00"))}
                          for line in commitment["sov"]],
                "periods": [self.base._period(row["id"]) for row in self.cipher.db.query("SELECT id FROM periods WHERE status='open' ORDER BY start_date,id")],
                "priorBill": {"id": prior["id"], "sequence": prior["sequence"], "status": prior["status"]} if prior else None,
                "availableActions": (["bill.prepare"] if accounting and not blocks else []) + (["invoice.receive"] if accounting and not has_stored and not is_purchase_order else []), "blockedReasons": blocks}

    @_locked
    def preparation(self, person_id, commitment_id):
        return self._preparation(self.base._authority(person_id), commitment_id)

    def _invoice_value(self, authority, inv):
        evidence = self._evidence(authority, inv["evidence_revision_id"])
        commitment = self._commitment(authority, inv["commitment_id"]) if inv["commitment_id"] else None
        current = next((attempt for attempt in self._attempts(inv) if attempt["id"] == inv["match_attempt_id"]), None)
        facts = loads(current["result_json"]) if current else None
        bill_id = (facts["bill"] or {}).get("id") if facts else None
        if bill_id:
            bill = self.base._bill(authority, bill_id)
            if commitment is None or bill["commitment_id"] != commitment["id"]:
                _invalid_record()
        blocks = []
        if inv["possible_duplicate"] and not inv["duplicate_cleared_at"]:
            blocks.append({"code": "possible_duplicate", "message": EXCEPTIONS["possible_duplicate"], "target": "invoice"})
        if not evidence["is_current"]:
            blocks.append({"code": "evidence_stale", "message": EXCEPTIONS["evidence_stale"], "target": "evidence"})
        is_purchase_order = facts is not None and facts["basis"] != "progress"
        if not facts:
            is_purchase_order = self.ap._facts(inv)["basis"] != "progress"
        if is_purchase_order:
            blocks.append({"code": "unsupported_purchase_order", "message": "This practice workflow currently supports progress subcontract matching.", "target": "invoice"})
        actions = []
        if authority.allows(inv["project_id"], "accountant") and not is_purchase_order:
            try:
                self.ap.match_preflight(inv["id"])
                actions.append("invoice.computeMatch")
            except (RuntimeError, ValueError, TypeError, KeyError):
                pass
            try:
                self.cipher.check_request_approval(MATCH_OPERATION, inv["id"], actor_role="accountant", requested_by=authority.login)
                actions.append("invoice.requestMatchApproval")
            except (RuntimeError, ValueError, TypeError, KeyError):
                pass
        return {**PROVENANCE, "id": inv["id"], "version": self._version(authority, inv["id"], "invoice"),
                "projectId": inv["project_id"], "projectName": self._project(authority, inv["project_id"])["name"],
                "commitmentId": inv["commitment_id"], "commitmentTitle": commitment["title"] if commitment else None,
                "supplierId": inv["supplier_id"], "supplierName": self.cipher.party(inv["supplier_id"])["name"],
                "invoiceNumber": inv["invoice_number"], "invoiceDate": inv["invoice_date"], "dueDate": inv["due_date"],
                "amountCents": _money(inv["amount"]), "status": inv["status"], "invoiceVersion": inv["version"],
                "evidence": {"documentId": evidence["document_id"], "revisionId": evidence["id"], "title": evidence["title"], "revision": evidence["revision"], "isCurrent": evidence["is_current"]},
                "possibleDuplicate": bool(inv["possible_duplicate"]), "duplicateBlocking": bool(inv["possible_duplicate"] and not inv["duplicate_cleared_at"]),
                "match": {"status": facts["status"], "basis": facts["basis"], "exceptions": [{"code": code, "message": EXCEPTIONS[code]} for code in facts["exceptions"]],
                          "billId": bill_id, "attemptId": current["id"]} if facts else None,
                "matchApprovalId": inv["match_approval_id"], "availableActions": actions, "blockedReasons": blocks}

    @_locked
    def invoice(self, person_id, invoice_id):
        authority = self.base._authority(person_id)
        return self._invoice_value(authority, self._invoice(authority, invoice_id))

    def _effective(self, approval):
        if approval["status"] not in ("pending", "granted"):
            return approval["status"]
        if parse_iso(approval["expires_at"]) <= utcnow():
            return "expired"
        try:
            current = self.cipher._manifest(MATCH_OPERATION, approval["subject_id"], "accountant")
            if material_hash(current) != approval["material_hash"] or current.get("governance") != approval["manifest"].get("governance"):
                return "stale"
        except (RuntimeError, ValueError, TypeError, KeyError):
            return "stale"
        return approval["status"]

    def _approval_value(self, authority, approval):
        inv = self._invoice(authority, approval["subject_id"])
        return {"id": approval["id"], "approvalId": approval["id"], "version": self._version(authority, approval["id"], "approval"),
                "projectId": inv["project_id"], "projectName": self._project(authority, inv["project_id"])["name"],
                "invoiceId": inv["id"], "invoiceNumber": inv["invoice_number"], "supplierName": self.cipher.party(inv["supplier_id"])["name"],
                "status": approval["status"], "effectiveStatus": self._effective(approval), "requestedBy": self.base._person(approval["requested_by"]),
                "approvedBy": self.base._person(approval["approver"]), "requestedAt": approval["requested_at"],
                "approvedAt": approval["granted_at"], "expiresAt": approval["expires_at"], "amountCents": _money(approval["manifest"]["amounts"]["invoice_amount"])}

    @_locked
    def packet(self, person_id, approval_id):
        authority = self.base._authority(person_id)
        approval = self._approval(authority, approval_id)
        inv = self._invoice(authority, approval["subject_id"])
        value = self._approval_value(authority, approval)
        bound = approval["manifest"]["bindings"]
        bound_facts = {"invoiceNumber": bound["invoice_number"], "invoiceDate": bound["invoice_date"], "dueDate": bound["due_date"],
                       "amountCents": value["amountCents"], "evidenceRevisionId": bound["evidence_revision_id"],
                       "billId": (bound["bill"] or {}).get("id"), "billStatus": (bound["bill"] or {}).get("status")}
        current_facts = {"invoiceNumber": inv["invoice_number"], "invoiceDate": inv["invoice_date"], "dueDate": inv["due_date"],
                         "amountCents": _money(inv["amount"]), "evidenceRevisionId": inv["evidence_revision_id"], "billId": inv["matched_bill_id"], "billStatus": None}
        current_revision = self.cipher.evidence.current_revision(inv["evidence_document_id"])
        if current_revision:
            current_facts["evidenceRevisionId"] = self._evidence(authority, current_revision["id"])["id"]
        try:
            facts = self.ap._facts(inv)
            current_facts["billId"] = (facts["bill"] or {}).get("id")
            current_facts["billStatus"] = (facts["bill"] or {}).get("status")
        except (RuntimeError, ValueError, TypeError, KeyError):
            pass
        for reference in (bound_facts["billId"], current_facts["billId"]):
            if reference:
                self.base._bill(authority, reference)
        actions = []
        supported = bound.get("basis") == "progress"
        if authority.allows(inv["project_id"], "accountant") and supported and value["effectiveStatus"] in ("pending", "granted"):
            if value["effectiveStatus"] == "pending":
                try:
                    self.cipher.check_invoice_match_grant(approval_id, approver=authority.login, approver_role="accountant")
                    actions.append("invoice.approveMatch")
                except (RuntimeError, ValueError, TypeError, KeyError):
                    pass
            else:
                try:
                    self.cipher.check_invoice_match_execution(approval_id, actor=authority.login)
                    actions.append("invoice.executeMatch")
                except (RuntimeError, ValueError, TypeError, KeyError):
                    pass
        return {**PROVENANCE, **value, "invoice": self._invoice_value(authority, inv), "boundFacts": bound_facts, "currentFacts": current_facts,
                "changes": [{"field": key, "before": bound_facts[key], "after": current_facts[key]} for key in bound_facts if bound_facts[key] != current_facts[key]],
                "effect": {"invoiceStatus": "matched", "billLinked": bool(bound_facts["billId"]), "workingLedgerJournalDelta": 0, "apPayableDeltaCents": 0},
                "availableActions": actions, "blockedReasons": [{"code": "unsupported_purchase_order", "message": "This practice workflow currently supports progress subcontract matching.", "target": "invoice"}]
                if not supported else [] if value["effectiveStatus"] in ("pending", "granted") else [{"code": "approval_unavailable", "message": "This match authorization requires a fresh review.", "target": "approval"}]}

    @_locked
    def read(self, person_id, collection, *, project_id=None, status=None, search=None, top=50, cursor=None):
        if not isinstance(collection, str) or collection not in STATUSES:
            raise APRefusal(422, "unknown_collection", "Choose a supported invoice practice collection.", "collection")
        if type(top) is not int or not 1 <= top <= 100:
            raise APRefusal(422, "invalid_query", "Page size must be an integer from 1 through 100.", "top")
        if project_id is not None and (not isinstance(project_id, str) or not project_id or len(project_id) > 200 or project_id != project_id.strip() or any(ord(char) < 32 for char in project_id)):
            raise APRefusal(422, "invalid_query", "Choose a valid practice project ID.", "projectId")
        if status is not None and status not in STATUSES[collection]:
            raise APRefusal(422, "invalid_query", "Choose a supported status for this collection.", "status")
        if search is not None and (not isinstance(search, str) or len(search) > 200 or any(ord(char) < 32 for char in search)):
            raise APRefusal(422, "invalid_query", "Search must be text of at most 200 characters.", "search")
        if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 2048):
            raise APRefusal(422, "invalid_query", "Choose a valid practice paging cursor.", "cursor")
        search = search.strip().casefold() or None if search is not None else None
        authority = self.base._authority(person_id)
        if project_id is not None:
            self._project(authority, project_id)
        projects = (project_id,) if project_id else authority.project_ids
        pairs = []
        for project in projects:
            self._project(authority, project)
            if collection == "invoices":
                for row in self.cipher.db.query("SELECT id,created_at FROM ap_invoices WHERE project_id=? ORDER BY created_at,id", (project,)):
                    pairs.append(((row["created_at"], row["id"]), self._invoice_value(authority, self._invoice(authority, row["id"]))))
            elif collection == "match-approvals":
                for row in self.cipher.db.query("SELECT a.id,a.requested_at FROM approvals a JOIN ap_invoices i ON a.subject_type='ap_invoice' AND a.subject_id=i.id WHERE a.operation=? AND i.project_id=? ORDER BY a.requested_at,a.id", (MATCH_OPERATION, project)):
                    pairs.append(((row["requested_at"], row["id"]), self._approval_value(authority, self._approval(authority, row["id"]))))
            else:
                for row in self.cipher.db.query("SELECT d.id,d.created_at,r.id AS revision_id FROM documents d JOIN document_revisions r ON r.document_id=d.id WHERE d.project_id=? AND d.kind='supplier_invoice' AND r.revision=(SELECT MAX(revision) FROM document_revisions WHERE document_id=d.id) ORDER BY d.created_at,d.id", (project,)):
                    evidence = self._evidence(authority, row["revision_id"])
                    available = self._evidence_available(authority, row["id"])
                    value = {"id": row["id"], "documentId": row["id"], "revisionId": evidence["id"], "projectId": project,
                             "title": evidence["title"], "revision": evidence["revision"], "isCurrent": True, "available": available,
                             "status": "available" if available else "in_use"}
                    pairs.append(((row["created_at"], row["id"]), value))
        binding = self._sign({"provenance": PROVENANCE, "collection": collection, "person": authority.person_id,
                              "scope": authority.scope_hash, "project": project_id, "status": status, "search": search, "top": top, "sort": "createdAt,id"})
        last = self.base._cursor_key(cursor, binding)
        pairs.sort(key=lambda item: item[0])
        if status is not None:
            pairs = [item for item in pairs if item[1]["status"] == status]
        if search:
            pairs = [item for item in pairs if any(search in str(item[1].get(key) or "").casefold() for key in
                                                  ("invoiceNumber", "supplierName", "projectName", "commitmentTitle", "title"))]
        values = [value for _, value in pairs]
        totals = {"amountCents": sum(value["amountCents"] for value in values if value["status"] != "rejected")} if collection == "invoices" else {}
        if any(abs(value) > MAX_SAFE_INTEGER for value in totals.values()):
            raise APRefusal(422, "amount_out_of_range", "The total exceeds this practice client's exact integer range.", "totals")
        selected = [item for item in pairs if last is None or item[0] > last]
        page = selected[:top]
        next_cursor = self.base._token({"v": 1, "binding": binding, "last": list(page[-1][0])}) if len(selected) > top else None
        facets = [{"value": value, "count": sum(item["status"] == value for item in values)} for value in sorted({item["status"] for item in values})]
        return {**PROVENANCE, "collection": collection, "projectId": project_id, "value": [value for _, value in page],
                "count": len(values), "nextCursor": next_cursor, "facets": {"statuses": facets}, "totals": totals}
