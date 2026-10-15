"""Governed payee destination changes (plan section 6: a separate bank-detail maintainer, and
vendor bank changes verified independently through a trusted channel): request, verification
evidence, the two-person rule, the ``party.verify_destination`` approval, staleness when another
change lands, invalidation of approvals naming the old destination, dispatch to the verified
destination only, schema guards and the compatibility helper."""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.tests.bill_helpers import approve_and_post_bill
from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.domain.payments import (
    DESTINATION_SCHEMA_NAME, DESTINATION_VERIFICATION_SCHEMA_NAME, VERIFICATION_CHANNELS, VERIFY_DESTINATION_OPERATION, DestinationChangeError,
    DestinationChangeStale, PaymentError, destination_fingerprint,
)
from apps.cipher.service import Cipher, RoleNotAuthorized, run_golden_fixture

D = Decimal
ENTITY = "S&A Solutions LLC (synthetic)"
OLD = "ACH-SIM-PAYEE-0001"
NEW = "ACH-SIM-PAYEE-0002"
OTHER = "ACH-SIM-PAYEE-0003"
CALL_BACK = "call-back to number on file"
LETTER = "signed letter on letterhead"


class World:
    """A supplier whose destination OLD was seeded through the fixture path (version 2,
    verified), a project with an executed 100,000 subcontract and an open period P1."""

    def __init__(self, path: str = ":memory:"):
        self.c = Cipher(path)
        sup = self.c.add_party(kind="supplier", name="Synthetic Sheet Pile Subcontractor", destination=OLD)
        self.supplier = self.c.verify_destination(sup["id"], destination=OLD, verified_by="owner")
        self.sid = self.supplier["id"]
        self.customer = self.c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.project = self.c.create_project(name="Cofferdam and dewatering", entity=ENTITY, budget="115000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        cmt = self.c.commitments.create(project_id=self.pid, supplier_id=self.sid, title="Sheet piling, cofferdam and dewatering",
                                        sov_lines=[{"description": "Sheet piling", "amount": "60000"}, {"description": "Dewatering", "amount": "40000"}], actor="pm")
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        self.cmt = self.c.commitments.get(cmt["id"])
        self.line1 = self.cmt["sov"][0]["id"]
        self._docs = 0

    @property
    def p(self):
        return self.c.payments

    def evidence(self, label: str = "call-back notes") -> str:
        """Register an evidence document and return its revision's content hash."""
        self._docs += 1
        doc = self.c.evidence.register_document(project_id=self.pid, kind="destination_verification", title=f"Payee verification {self._docs}: {label}", actor="bank-admin")
        rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic verification record {self._docs}: {label}".encode(), note=label, actor="bank-admin")
        return rev["content_hash"]

    def evidenced_change(self, new: str = NEW, *, requested_by: str = "ap-clerk", verified_by: str = "ext-accountant", channel: str = CALL_BACK) -> dict:
        ch = self.p.request_destination_change(self.sid, new, requested_by, "supplier letter announcing a new bank account", "ap-clerk")
        return self.p.record_verification_evidence(ch["id"], channel, verified_by, self.evidence(), "bank-admin")

    def granted(self, change_id: str, *, role: str = "bank_admin") -> dict:
        ap = self.c.request_approval(VERIFY_DESTINATION_OPERATION, change_id, actor_role=role, requested_by="bank-admin")
        return self.c.approve(ap["id"], approver="owner", approver_role="owner")

    def execute_change(self, change_id: str):
        ap = self.granted(change_id)
        return self.c.execute(ap["id"], actor="bank-admin")

    def posted_bill(self, cumulative: str) -> dict:
        b = self.c.bills.certify(commitment_id=self.cmt["id"], period_id="P1", installed=[{"sov_line_id": self.line1, "cumulative_installed": cumulative}], actor="pm")
        approve_and_post_bill(self.c, b["id"], approver="owner", approver_role="owner", poster="accountant")
        return self.c.bills.get(b["id"])

    def release(self, bill_id: str) -> dict:
        res = self.c.approve_and_execute("payment.release", bill_id, actor_role="treasury", actor="treasury")
        return self.p.get(res.result["intent"])

    def party(self) -> dict:
        return self.c.party(self.sid)

    def assert_books(self, tc):
        tc.assertTrue(self.c.ledger.trial_balance()["balanced"])
        tc.assertTrue(self.c.audit.verify_chain()["ok"])
        tc.assertTrue(self.c.bills.ap_open_items(self.pid)["reconciled"])
        tc.assertTrue(self.p.clearing_items()["reconciled"])

    def plaintext_leaks(self, destination: str) -> list[str]:
        """Stored places other than the change row that hold ``destination`` in plain text, also
        when spelled without case, spaces or punctuation ('ach sim payee 0002')."""
        core = "".join(ch for ch in destination.casefold() if ch.isalnum())
        leaks = []
        for table, column in (("audit_log", "payload_json"), ("audit_log", "actor"), ("approvals", "manifest_json"), ("approvals", "requested_by"),
                              ("approvals", "invalidated_reason"), ("idempotency", "result_json"), ("destination_changes", "reason"),
                              ("destination_changes", "requested_by"), ("destination_changes", "requested_actor"), ("destination_changes", "verified_by"),
                              ("destination_changes", "evidence_recorded_by"), ("destination_changes", "closed_reason"), ("destination_changes", "executed_by")):
            for (text,) in self.c.db.conn.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL"):
                if core in "".join(ch for ch in str(text).casefold() if ch.isalnum()):
                    leaks.append(f"{table}.{column}")
                    break
        return leaks


class GovernedChangeTests(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.c = self.w.c

    def test_request_evidence_approval_and_execution_change_the_destination_once(self):
        w, c = self.w, self.c
        self.assertEqual((w.supplier["destination_version"], w.supplier["destination_verified"]), (2, 1))
        req = w.p.request_destination_change(w.sid, f"  {NEW} ", "ap-clerk", "supplier letter announcing a new bank account", "ap-clerk")
        self.assertEqual((req["status"], req["version"], req["old_destination_version"], req["requested_by"]), ("pending", 1, 2, "ap-clerk"))
        self.assertEqual((req["old_destination_hash"], req["new_destination_hash"]), (destination_fingerprint(OLD), destination_fingerprint(NEW)))
        self.assertNotIn("new_destination", req)
        self.assertEqual(req["new_destination_masked"], "****0002")
        self.assertEqual((w.party()["destination"], w.party()["destination_version"]), (OLD, 2))  # nothing moves on a request
        evidence = w.evidence("call-back to the number in the supplier master file")
        ev = w.p.record_verification_evidence(req["id"], "Call-back to number on file", "ext-accountant", evidence, "bank-admin")
        self.assertEqual((ev["status"], ev["version"], ev["channel"], ev["verified_by"], ev["evidence_hash"], ev["evidence_recorded_by"]),
                         ("evidenced", 2, CALL_BACK, "ext-accountant", evidence, "bank-admin"))
        self.assertEqual(w.party()["destination"], OLD)

        ap = c.request_approval(VERIFY_DESTINATION_OPERATION, req["id"], actor_role="bank_admin", requested_by="bank-admin")
        m = ap["manifest"]
        self.assertEqual((m["operation"], m["subject"], m["actor_role"]), (VERIFY_DESTINATION_OPERATION, {"type": "destination_change", "id": req["id"]}, "bank_admin"))
        b = m["bindings"]
        self.assertEqual((b["change_id"], b["old_destination_version"], b["new_destination_version"], b["evidence_hash"], b["channel"], b["verified_by"], b["requested_by"]),
                         (req["id"], 2, 3, evidence, CALL_BACK, "ext-accountant", "ap-clerk"))
        self.assertEqual((b["old_destination_hash"], b["new_destination_hash"]), (destination_fingerprint(OLD), destination_fingerprint(NEW)))
        self.assertEqual(m["destination"], {"party_id": w.sid, "destination_hash": destination_fingerprint(OLD), "destination_version": 2})
        c.approve(ap["id"], approver="owner", approver_role="owner")
        res = c.execute(ap["id"], actor="bank-admin")
        self.assertFalse(res.replayed)
        self.assertEqual((res.result["status"], res.result["destination_version"], res.result["previous_version"], res.result["superseded_changes"]),
                         ("executed", 3, 2, []))
        party = w.party()
        self.assertEqual((party["destination"], party["destination_version"], party["destination_verified"]), (NEW, 3, 1))
        [hist] = w.p.change_history(w.sid)
        self.assertEqual((hist["id"], hist["status"], hist["approval_id"], hist["executed_by"], hist["new_destination_version"], hist["is_current_destination"], hist["open"]),
                         (req["id"], "executed", ap["id"], "bank-admin", 3, True, False))
        self.assertEqual([a["status"] for a in hist["approvals"]], ["consumed"])
        self.assertNotIn("new_destination", hist)
        self.assertEqual(c.approvals.get(ap["id"])["status"], "consumed")
        # replay of the same execution changes nothing; the executed change cannot be approved again
        again = c.execute(ap["id"], actor="bank-admin")
        self.assertTrue(again.replayed)
        self.assertEqual(w.party()["destination_version"], 3)
        with self.assertRaises(DestinationChangeStale):
            c.request_approval(VERIFY_DESTINATION_OPERATION, req["id"], actor_role="bank_admin")
        actions = [e["action"] for e in c.audit.entries(entity_id=req["id"])]
        for action in ("party.destination_change_requested", "party.destination_change_evidenced", "party.destination_change_executed"):
            self.assertIn(action, actions)
        verified = [json.loads(e["payload_json"]) for e in c.audit.entries(entity_id=w.sid) if e["action"] == "party.destination_verified"]
        self.assertEqual((verified[-1]["destination_hash"], verified[-1]["version"], verified[-1]["governed"], verified[-1]["change_id"]),
                         (destination_fingerprint(NEW), 3, True, req["id"]))
        # the new destination lives only in the change row (and the party): never in audit, manifests or command results
        self.assertEqual(w.plaintext_leaks(NEW), [])
        exported = c.audit_export()["tables"]["destination_changes"]["rows"][0]
        self.assertTrue(exported["new_destination"].startswith("sha256:"))
        w.assert_books(self)

    def test_the_requester_can_never_be_the_verifier(self):
        w, c = self.w, self.c
        req = w.p.request_destination_change(w.sid, NEW, "owner", "owner keyed a new bank account from a supplier e-mail", "owner")
        evidence = w.evidence()
        for same in ("owner", " OWNER ", "Owner"):
            with self.assertRaisesRegex(DestinationChangeError, "two logins by one owner are not separation and an outside verifier is required"):
                w.p.record_verification_evidence(req["id"], CALL_BACK, same, evidence, "owner")
        self.assertEqual(w.p.destination_change(req["id"])["status"], "pending")
        # the schema refuses the same shortcut through raw SQL
        rev = c.db.one("SELECT id FROM document_revisions WHERE content_hash=?", (evidence,))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "verifier other than the requester"):
            c.db.execute(
                """UPDATE destination_changes SET status='evidenced', version=version+1, channel=?, verified_by='owner', evidence_hash=?, evidence_revision_id=?,
                   evidence_recorded_by='owner', evidenced_at='2026-10-12T00:00:00Z' WHERE id=?""",
                (CALL_BACK, evidence, rev["id"], req["id"]),
            )
        # a sole owner gets separation from an outside verifier, then approves and executes as owner
        w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", evidence, "owner")
        ap = c.request_approval(VERIFY_DESTINATION_OPERATION, req["id"], actor_role="owner", requested_by="owner")
        c.approve(ap["id"], approver="owner", approver_role="owner")
        self.assertEqual(c.execute(ap["id"], actor="owner").result["status"], "executed")
        self.assertEqual(w.party()["destination"], NEW)

    def test_verification_evidence_is_required_and_must_be_a_current_stored_revision_used_once(self):
        w, c = self.w, self.c
        req = w.p.request_destination_change(w.sid, NEW, "ap-clerk", "new bank", "ap-clerk")
        with self.assertRaisesRegex(DestinationChangeError, "no verification evidence"):
            c.request_approval(VERIFY_DESTINATION_OPERATION, req["id"], actor_role="bank_admin")
        evidence = w.evidence()
        for channel in ("e-mail from the supplier", "phone number in the request", "", None, 3):
            with self.assertRaisesRegex(DestinationChangeError, "verification channel must be one of"):
                w.p.record_verification_evidence(req["id"], channel, "ext-accountant", evidence, "bank-admin")
        with self.assertRaisesRegex(DestinationChangeError, "does not match any stored evidence revision"):
            w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", "0" * 64, "bank-admin")
        doc = c.evidence.register_document(project_id=w.pid, kind="destination_verification", title="Letter, two revisions", actor="bank-admin")
        rev1 = c.evidence.add_revision(document_id=doc["id"], content=b"synthetic letter, unsigned draft", actor="bank-admin")
        c.evidence.add_revision(document_id=doc["id"], content=b"synthetic letter, signed", actor="bank-admin")
        with self.assertRaisesRegex(DestinationChangeError, "superseded revision 1"):
            w.p.record_verification_evidence(req["id"], LETTER, "ext-accountant", rev1["content_hash"], "bank-admin")
        for bad in ("", "  ", None):
            with self.assertRaises(DestinationChangeError):
                w.p.record_verification_evidence(req["id"], CALL_BACK, bad, evidence, "bank-admin")
        self.assertEqual(w.p.destination_change(req["id"])["status"], "pending")
        w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", evidence, "bank-admin")
        with self.assertRaisesRegex(DestinationChangeError, "already recorded"):
            w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", w.evidence(), "bank-admin")
        other = w.p.request_destination_change(w.sid, OTHER, "ap-clerk", "second account", "ap-clerk")
        with self.assertRaisesRegex(DestinationChangeError, "already verified destination change"):
            w.p.record_verification_evidence(other["id"], CALL_BACK, "ext-accountant", evidence, "bank-admin")
        self.assertEqual(set(VERIFICATION_CHANNELS), {"call-back to number on file", "in-person", "signed letter on letterhead"})
        # nothing but an executed approval moves a change to executed
        with self.assertRaisesRegex(sqlite3.DatabaseError, "consumed party.verify_destination approval"):
            c.db.execute("UPDATE destination_changes SET status='executed', version=version+1, executed_by='x', executed_at='t', new_destination_version=3 WHERE id=?", (req["id"],))

    def test_an_approval_goes_stale_when_another_change_lands(self):
        w, c = self.w, self.c
        a = w.evidenced_change(NEW)
        b = w.evidenced_change(OTHER, verified_by="ext-auditor", channel="in-person")
        ap_a, ap_b = w.granted(a["id"]), w.granted(b["id"])
        res = c.execute(ap_a["id"], actor="bank-admin").result
        self.assertEqual(res["superseded_changes"], [b["id"]])
        self.assertIn(ap_b["id"], res["invalidated_approvals"])
        self.assertEqual(c.approvals.get(ap_b["id"])["status"], "invalidated")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap_b["id"], actor="bank-admin")
        got_b = w.p.destination_change(b["id"])
        self.assertEqual((got_b["status"], got_b["superseded_by"], got_b["open"]), ("superseded", a["id"], False))
        self.assertEqual((w.party()["destination"], w.party()["destination_version"]), (NEW, 3))
        with self.assertRaises(DestinationChangeStale):
            c.request_approval(VERIFY_DESTINATION_OPERATION, b["id"], actor_role="bank_admin")

        # the fixture path landing in between makes a granted change stale too
        c2 = w.evidenced_change(OTHER)
        ap_c = w.granted(c2["id"])
        c.verify_destination(w.sid, destination="ACH-SIM-PAYEE-0004", verified_by="bank-admin")
        self.assertEqual(c.approvals.get(ap_c["id"])["status"], "invalidated")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap_c["id"], actor="bank-admin")
        self.assertTrue(w.p.destination_change(c2["id"])["stale"])
        self.assertEqual(w.party()["destination"], "ACH-SIM-PAYEE-0004")
        with self.assertRaises(DestinationChangeStale):
            c.request_approval(VERIFY_DESTINATION_OPERATION, c2["id"], actor_role="bank_admin")

    def test_a_new_revision_of_the_evidence_after_approval_makes_it_stale(self):
        w, c = self.w, self.c
        ch = w.evidenced_change(NEW)
        ap = w.granted(ch["id"])
        rev = c.db.one("SELECT document_id FROM document_revisions WHERE id=?", (ch["evidence_revision_id"],))
        c.evidence.add_revision(document_id=rev["document_id"], content=b"synthetic verification record, amended", actor="bank-admin")
        with self.assertRaisesRegex(StaleApprovalError, "superseded by revision 2"):
            c.execute(ap["id"], actor="bank-admin")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(w.party()["destination"], OLD)

    def test_a_change_whose_evidence_was_superseded_cannot_be_approved_or_executed_afresh(self):
        """Review finding: a fresh approval requested after the evidence document gained a new
        revision used to bind evidence_is_current_revision False and execute."""
        w, c = self.w, self.c
        ch = w.evidenced_change(NEW)
        doc_id = c.db.scalar("SELECT document_id FROM document_revisions WHERE id=?", (ch["evidence_revision_id"],))
        c.evidence.add_revision(document_id=doc_id, content=b"AMENDED: supplier called back and DENIED sending any bank change", actor="bank-admin")
        got = w.p.destination_change(ch["id"])
        self.assertEqual((got["status"], got["open"], got["stale"], got["evidence_current"]), ("evidenced", True, True, False))
        with self.assertRaisesRegex(DestinationChangeStale, "superseded by revision 2 after it was recorded.*withdraw it and request the change again"):
            c.request_approval(VERIFY_DESTINATION_OPERATION, ch["id"], actor_role="bank_admin", requested_by="bank-admin")
        for role in ("bank_admin", "owner"):
            with self.assertRaises(DestinationChangeStale):
                c.approve_and_execute(VERIFY_DESTINATION_OPERATION, ch["id"], actor_role=role, actor="bank-admin")
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM approvals WHERE operation=?", (VERIFY_DESTINATION_OPERATION,)), 0)
        self.assertEqual((w.party()["destination"], w.party()["destination_version"]), (OLD, 2))
        # evidence is recorded once per change, so the change is withdrawn and requested again with fresh verification
        with self.assertRaisesRegex(DestinationChangeError, "already recorded"):
            w.p.record_verification_evidence(ch["id"], CALL_BACK, "ext-accountant", w.evidence(), "bank-admin")
        withdrawn = w.p.withdraw_destination_change(ch["id"], "evidence amended: the supplier denied sending a bank change", "bank-admin")
        self.assertEqual((withdrawn["status"], withdrawn["stale"]), ("withdrawn", False))
        again = w.evidenced_change(NEW)
        self.assertEqual((again["evidence_current"], again["stale"]), (True, False))
        self.assertEqual(w.execute_change(again["id"]).result["status"], "executed")
        self.assertEqual([(h["status"], h["is_current_destination"]) for h in w.p.change_history(w.sid)], [("withdrawn", False), ("executed", True)])
        self.assertEqual(w.party()["destination"], NEW)
        self.assertEqual(w.plaintext_leaks(NEW), [])
        w.assert_books(self)

    def test_the_schema_refuses_executing_a_change_whose_evidence_is_no_longer_current(self):
        w, c = self.w, self.c
        ch = w.evidenced_change(NEW)
        ap = w.granted(ch["id"])
        # emulate every governed step by raw SQL: a consumed approval, then the executed transition
        c.db.execute("UPDATE approvals SET status='consumed', consumed_at='2026-10-12T00:00:00Z', consumed_by='raw' WHERE id=?", (ap["id"],))
        doc_id = c.db.scalar("SELECT document_id FROM document_revisions WHERE id=?", (ch["evidence_revision_id"],))
        c.evidence.add_revision(document_id=doc_id, content=b"synthetic verification record, retracted", actor="bank-admin")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "while that evidence revision is still current"):
            c.db.execute("UPDATE destination_changes SET status='executed', version=version+1, approval_id=?, executed_by='raw', executed_at='t', "
                         "new_destination_version=3 WHERE id=?", (ap["id"], ch["id"]))
        self.assertEqual(w.p.destination_change(ch["id"])["status"], "evidenced")
        self.assertIn(DESTINATION_VERIFICATION_SCHEMA_NAME, [v["name"] for v in c.db.schema_status()["versions"] if v["applied"]])

    def test_the_verifier_cannot_be_the_login_that_recorded_the_request(self):
        """Review finding: the two-person rule compared only the typed requester name."""
        w, c = self.w, self.c
        req = w.p.request_destination_change(w.sid, NEW, "ap-clerk", "supplier letter announcing a new bank account", "owner")
        self.assertEqual((req["requested_by"], req["requested_actor"]), ("ap-clerk", "owner"))
        evidence = w.evidence()
        for same in ("owner", " OWNER ", "Owner"):
            with self.assertRaisesRegex(DestinationChangeError, "recorded the request for this destination change.*two logins by one owner are not "
                                                                "separation and an outside verifier is required"):
                w.p.record_verification_evidence(req["id"], CALL_BACK, same, evidence, "owner")
        rev = c.db.one("SELECT id FROM document_revisions WHERE content_hash=?", (evidence,))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "a verifier other than the requester and the requesting login"):
            c.db.execute(
                """UPDATE destination_changes SET status='evidenced', version=version+1, channel=?, verified_by='owner', evidence_hash=?, evidence_revision_id=?,
                   evidence_recorded_by='owner', evidenced_at='2026-10-12T00:00:00Z' WHERE id=?""",
                (CALL_BACK, evidence, rev["id"], req["id"]),
            )
        self.assertEqual(w.p.destination_change(req["id"])["status"], "pending")
        # the owner may record an outside verifier's call-back
        ev = w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", evidence, "owner")
        self.assertEqual((ev["status"], ev["verified_by"], ev["evidence_recorded_by"]), ("evidenced", "ext-accountant", "owner"))
        manifest = c.request_approval(VERIFY_DESTINATION_OPERATION, req["id"], actor_role="owner", requested_by="owner")["manifest"]
        self.assertEqual((manifest["bindings"]["requested_actor"], manifest["bindings"]["verified_by"]), ("owner", "ext-accountant"))

    def test_evidence_must_be_a_destination_verification_record(self):
        """Review finding: any stored revision (an invoice the requester uploaded) counted as evidence."""
        w, c = self.w, self.c
        req = w.p.request_destination_change(w.sid, NEW, "ap-clerk", "remit-to change on a supplier invoice", "ap-clerk")
        invoice = c.evidence.register_document(project_id=w.pid, kind="invoice", title="Supplier invoice with new remit-to", actor="ap-clerk")
        inv_rev = c.evidence.add_revision(document_id=invoice["id"], content=b"synthetic invoice: remit to the new account", actor="ap-clerk")
        with self.assertRaisesRegex(DestinationChangeError, "document of kind 'invoice', not a 'destination_verification' record"):
            w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", inv_rev["content_hash"], "ap-clerk")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "the current revision of a destination_verification document"):
            c.db.execute(
                """UPDATE destination_changes SET status='evidenced', version=version+1, channel=?, verified_by='ext-accountant', evidence_hash=?,
                   evidence_revision_id=?, evidence_recorded_by='ap-clerk', evidenced_at='2026-10-12T00:00:00Z' WHERE id=?""",
                (CALL_BACK, inv_rev["content_hash"], inv_rev["id"], req["id"]),
            )
        self.assertEqual(w.p.destination_change(req["id"])["status"], "pending")
        with self.assertRaisesRegex(DestinationChangeError, "no verification evidence"):
            c.request_approval(VERIFY_DESTINATION_OPERATION, req["id"], actor_role="bank_admin")
        ev = w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", w.evidence("call-back to the number on file"), "bank-admin")
        self.assertEqual((ev["status"], ev["evidence_current"]), ("evidenced", True))

    def test_free_text_that_repeats_the_new_destination_never_reaches_the_audit_log(self):
        """Review finding: only the request's reason and requester were checked, by exact substring."""
        w, c = self.w, self.c
        spellings = (NEW, NEW.lower(), "ACH SIM PAYEE 0002", "ach.sim.payee.0002", "AchSimPayee0002")
        for spelling in spellings:
            for field, args in (("reason", ("ap-clerk", f"pay {spelling} now", "ap-clerk")),
                                ("requester", (f"clerk for {spelling}", "new bank", "ap-clerk")),
                                ("acting login", ("ap-clerk", "new bank", f"{spelling} desk"))):
                with self.assertRaisesRegex(DestinationChangeError, f"the {field} must not repeat the new destination"):
                    w.p.request_destination_change(w.sid, NEW, *args)
        self.assertEqual(w.p.change_history(w.sid), [])
        req = w.p.request_destination_change(w.sid, NEW, "ap-clerk", "supplier letter announcing a new bank account", "ap-clerk")
        evidence = w.evidence()
        with self.assertRaisesRegex(DestinationChangeError, "the verifier must not repeat the new destination"):
            w.p.record_verification_evidence(req["id"], CALL_BACK, "teller at ACH-SIM-PAYEE-0002", evidence, "bank-admin")
        with self.assertRaisesRegex(DestinationChangeError, "the acting login must not repeat the new destination"):
            w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", evidence, "ach sim payee 0002 desk")
        ch = w.p.record_verification_evidence(req["id"], CALL_BACK, "ext-accountant", evidence, "bank-admin")
        ap = w.granted(ch["id"])
        with self.assertRaisesRegex(DestinationChangeError, "the withdrawal reason must not repeat the new destination"):
            w.p.withdraw_destination_change(ch["id"], "supplier says ACH-SIM-PAYEE-0002 is not theirs", "bank-admin")
        with self.assertRaisesRegex(DestinationChangeError, "the acting login must not repeat the new destination"):
            w.p.withdraw_destination_change(ch["id"], "supplier says the new account is not theirs", "ACH SIM PAYEE 0002")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")  # nothing was withdrawn or invalidated
        with self.assertRaisesRegex(DestinationChangeError, "the acting login must not repeat the new destination"):
            c.execute(ap["id"], actor="ACH-SIM-PAYEE-0002 operator")
        self.assertEqual((c.approvals.get(ap["id"])["status"], w.party()["destination"]), ("granted", OLD))  # rolled back; the approval is still usable
        self.assertEqual(w.plaintext_leaks(NEW), [])
        self.assertEqual(c.execute(ap["id"], actor="bank-admin").result["status"], "executed")
        self.assertEqual(w.party()["destination"], NEW)
        self.assertEqual(w.plaintext_leaks(NEW), [])
        w.assert_books(self)

    def test_open_approvals_naming_the_old_destination_are_invalidated(self):
        w, c = self.w, self.c
        bill = w.posted_bill("20000")
        pay = c.request_approval("payment.release", bill["id"], actor_role="treasury", requested_by="treasury")
        c.approve(pay["id"], approver="treasury", approver_role="treasury")
        self.assertEqual((pay["manifest"]["destination"]["destination"], pay["manifest"]["destination"]["destination_version"]), (OLD, 2))
        draft = c.commitments.create(project_id=w.pid, supplier_id=w.sid, title="Follow-on dewatering", sov_lines=[{"description": "Wellpoints", "amount": "5000"}], actor="pm")
        cmt_ap = c.request_approval("commitment.execute", draft["id"], actor_role="pm", requested_by="pm")
        unrelated = c.add_party(kind="supplier", name="Unrelated supplier", destination="ACH-SIM-UNREL-0001")
        c.verify_destination(unrelated["id"], destination="ACH-SIM-UNREL-0001", verified_by="owner")
        res = w.execute_change(w.evidenced_change(NEW)["id"]).result
        self.assertEqual(set(res["invalidated_approvals"]), {pay["id"], cmt_ap["id"]})
        for ap_id in (pay["id"], cmt_ap["id"]):
            ap = c.approvals.get(ap_id)
            self.assertEqual(ap["status"], "invalidated")
            self.assertIn("payee destination changed after approval", ap["invalidated_reason"])
        with self.assertRaises(ApprovalNotGranted):
            c.execute(pay["id"], actor="treasury")
        fresh = w.release(bill["id"])
        self.assertEqual((fresh["destination"], fresh["destination_version"]), (NEW, 3))
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        self.assertEqual(c.provider.submissions[-1]["destination"], NEW)
        w.assert_books(self)

    def test_dispatch_uses_the_new_destination_only_after_the_change_executes(self):
        w, c = self.w, self.c
        bill1 = w.posted_bill("20000")
        first = w.release(bill1["id"])
        ch = w.evidenced_change(NEW)
        ap = w.granted(ch["id"])  # approved, not executed: payments still go to the verified destination
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        self.assertEqual((c.provider.submissions[-1]["destination"], c.provider.transfers[first["logical_op_id"]]["destination"]), (OLD, OLD))
        bill2 = w.posted_bill("30000")
        second = w.release(bill2["id"])
        self.assertEqual(second["destination"], OLD)
        res = c.execute(ap["id"], actor="bank-admin").result
        self.assertEqual(res["queued_intents_to_previous_destination"], [second["id"]])
        submissions = len(c.provider.submissions)
        [failed] = c.dispatch_payments()
        self.assertEqual((failed["intent_id"], failed["status"], failed["reason"]), (second["id"], "failed", "destination changed after approval"))
        self.assertEqual(len(c.provider.submissions), submissions)  # nothing went to the old destination
        self.assertEqual(c.bills.get(bill2["id"])["status"], "posted")
        retry = w.release(bill2["id"])
        self.assertEqual((retry["destination"], retry["destination_version"]), (NEW, 3))
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        self.assertEqual(c.provider.submissions[-1]["destination"], NEW)
        self.assertEqual(c.bills.get(bill2["id"])["status"], "paid")
        self.assertEqual(c.ledger.balance("1200"), D("-27000.00"))  # 18,000 + 9,000 in provider clearing, nothing twice
        w.assert_books(self)

    def test_duplicates_and_invalid_requests_are_refused(self):
        w, c = self.w, self.c
        with self.assertRaisesRegex(DestinationChangeError, "unknown party"):
            w.p.request_destination_change("pty_missing", NEW, "ap-clerk", "new bank", "ap-clerk")
        for bad in ("", "   ", None, 12345, "X" * 129):
            with self.assertRaises(DestinationChangeError):
                w.p.request_destination_change(w.sid, bad, "ap-clerk", "new bank", "ap-clerk")
        for field in ("requested_by", "reason", "actor"):
            args = {"party_id": w.sid, "new_destination": NEW, "requested_by": "ap-clerk", "reason": "new bank", "actor": "ap-clerk", field: " "}
            with self.assertRaises(DestinationChangeError):
                w.p.request_destination_change(**args)
        with self.assertRaisesRegex(DestinationChangeError, "must not repeat the new destination"):
            w.p.request_destination_change(w.sid, NEW, "ap-clerk", f"supplier asked us to pay {NEW.lower()} from now on", "ap-clerk")
        with self.assertRaisesRegex(DestinationChangeError, "already party .* verified destination"):
            w.p.request_destination_change(w.sid, OLD, "ap-clerk", "same account", "ap-clerk")
        first = w.p.request_destination_change(w.sid, NEW, "ap-clerk", "new bank", "ap-clerk")
        with self.assertRaisesRegex(DestinationChangeError, "already open"):
            w.p.request_destination_change(w.sid, NEW, "ap-clerk", "new bank again", "ap-clerk")
        with self.assertRaises(sqlite3.DatabaseError):  # and the schema refuses the duplicate too
            c.db.execute(
                """INSERT INTO destination_changes (id, party_id, requested_by, reason, requested_actor, old_destination_hash, old_destination_version,
                   new_destination, new_destination_hash, status, version, created_at) VALUES ('dch_raw',?,?,?,?,?,2,?,?,'pending',1,'t')""",
                (w.sid, "x", "x", "x", destination_fingerprint(OLD), NEW, destination_fingerprint(NEW)),
            )
        withdrawn = w.p.withdraw_destination_change(first["id"], "supplier confirmed by phone that no change was sent", "bank-admin")
        self.assertEqual((withdrawn["status"], withdrawn["closed_by"]), ("withdrawn", "bank-admin"))
        with self.assertRaisesRegex(DestinationChangeError, "only an open change"):
            w.p.withdraw_destination_change(first["id"], "again", "bank-admin")
        with self.assertRaises(DestinationChangeStale):
            c.request_approval(VERIFY_DESTINATION_OPERATION, first["id"], actor_role="bank_admin")
        with self.assertRaises(DestinationChangeError):
            w.p.record_verification_evidence(first["id"], CALL_BACK, "ext-accountant", w.evidence(), "bank-admin")
        second = w.p.request_destination_change(w.sid, NEW, "ap-clerk", "new bank, asked again", "ap-clerk")  # a withdrawn change no longer blocks
        self.assertEqual(second["status"], "pending")
        with self.assertRaisesRegex(DestinationChangeError, "unknown destination change"):
            w.p.destination_change("dch_missing")
        with self.assertRaisesRegex(DestinationChangeError, "unknown party"):
            w.p.change_history("pty_missing")
        self.assertEqual([h["status"] for h in w.p.change_history(w.sid)], ["withdrawn", "pending"])

    def test_withdrawing_an_approved_change_makes_its_approval_unusable(self):
        w, c = self.w, self.c
        ch = w.evidenced_change(NEW)
        ap = w.granted(ch["id"])
        withdrawn = w.p.withdraw_destination_change(ch["id"], "supplier called: the letter was not theirs", "bank-admin")
        self.assertEqual(withdrawn["status"], "withdrawn")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="bank-admin")
        self.assertEqual((w.party()["destination"], w.party()["destination_version"]), (OLD, 2))
        self.assertEqual([a["status"] for a in w.p.change_history(w.sid)[0]["approvals"]], ["invalidated"])

    def test_raw_sql_cannot_forge_alter_replace_or_delete_a_change(self):
        w, c = self.w, self.c
        ch = w.evidenced_change(NEW)
        cols = "id, party_id, requested_by, reason, requested_actor, old_destination_hash, old_destination_version, new_destination, new_destination_hash, status, version, created_at"
        with self.assertRaisesRegex(sqlite3.DatabaseError, "only as a pending request"):
            c.db.execute(f"INSERT INTO destination_changes ({cols}) VALUES ('dch_x',?,'x','x','x',?,2,'ACH-SIM-FORGED','h','executed',1,'t')", (w.sid, destination_fingerprint(OLD)))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "current destination version"):
            c.db.execute(f"INSERT INTO destination_changes ({cols}) VALUES ('dch_y',?,'x','x','x',?,1,'ACH-SIM-FORGED','h','pending',1,'t')", (w.sid, destination_fingerprint(OLD)))
        for sql in ("UPDATE destination_changes SET new_destination='ACH-SIM-FORGED' WHERE id=?",
                    "UPDATE destination_changes SET new_destination='ACH-SIM-FORGED', status='withdrawn', version=version+1, closed_by='x', closed_at='t', closed_reason='x' WHERE id=?"):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "request is immutable|move only"):
                c.db.execute(sql, (ch["id"],))
        self.assertEqual(c.db.scalar("SELECT new_destination FROM destination_changes WHERE id=?", (ch["id"],)), NEW)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "never replaced"):
            c.db.execute(f"INSERT OR REPLACE INTO destination_changes ({cols}) VALUES (?,?,'x','x','x',?,2,'ACH-SIM-FORGED','h2','pending',1,'t')",
                         (ch["id"], w.sid, destination_fingerprint(OLD)))
        with self.assertRaisesRegex(sqlite3.DatabaseError, "never deleted"):
            c.db.execute("DELETE FROM destination_changes WHERE id=?", (ch["id"],))
        self.assertEqual(w.p.destination_change(ch["id"])["status"], "evidenced")
        self.assertIn(DESTINATION_SCHEMA_NAME, [v["name"] for v in c.db.schema_status()["versions"] if v["applied"]])

    def test_only_the_bank_detail_maintainer_or_owner_holds_the_authority(self):
        w, c = self.w, self.c
        ch = w.evidenced_change(NEW)
        for role in ("treasury", "accountant", "controller", "pm", "reconciler", "viewer"):
            with self.assertRaises(RoleNotAuthorized):
                c.request_approval(VERIFY_DESTINATION_OPERATION, ch["id"], actor_role=role)
        ap = c.request_approval(VERIFY_DESTINATION_OPERATION, ch["id"], actor_role="bank_admin")
        for role in ("treasury", "accountant"):
            with self.assertRaises(RoleNotAuthorized):
                c.approve(ap["id"], approver="someone", approver_role=role)
        c.approve(ap["id"], approver="bank-admin-2", approver_role="bank_admin")
        self.assertEqual(c.execute(ap["id"], actor="bank-admin").result["status"], "executed")

    def test_the_compatibility_helper_requests_and_evidences_atomically(self):
        w, c = self.w, self.c
        evidence = w.evidence()
        with self.assertRaisesRegex(DestinationChangeError, "outside verifier is required"):
            w.p.governed_destination_change(w.sid, NEW, "owner", "owner", CALL_BACK, evidence, "owner")
        with self.assertRaisesRegex(DestinationChangeError, "recorded the request for this destination change"):  # the acting login cannot verify either
            w.p.governed_destination_change(w.sid, NEW, "ap-clerk", "bank-admin", CALL_BACK, evidence, "bank-admin")
        self.assertEqual(w.p.change_history(w.sid), [])  # all or nothing
        change_id = w.p.governed_destination_change(w.sid, NEW, "ap-clerk", "ext-accountant", CALL_BACK, evidence, "bank-admin")
        self.assertIsInstance(change_id, str)
        self.assertEqual(w.p.destination_change(change_id)["status"], "evidenced")
        self.assertEqual(w.party()["destination"], OLD)  # the caller still approves it
        res = c.approve_and_execute(VERIFY_DESTINATION_OPERATION, change_id, actor_role="bank_admin", actor="owner")
        self.assertEqual((res.result["status"], w.party()["destination"]), ("executed", NEW))

    def test_an_unverified_recorded_destination_is_verified_through_the_governed_path(self):
        w, c = self.w, self.c
        newco = c.add_party(kind="supplier", name="Synthetic Dewatering Supplier", destination="ACH-SIM-NEWCO-0001")
        self.assertEqual((newco["destination_version"], newco["destination_verified"]), (1, 0))
        change_id = w.p.governed_destination_change(newco["id"], "ACH-SIM-NEWCO-0001", "ap-clerk", "ext-accountant", "in-person", w.evidence(), "bank-admin")
        c.approve_and_execute(VERIFY_DESTINATION_OPERATION, change_id, actor_role="bank_admin", actor="bank-admin")
        got = c.party(newco["id"])
        self.assertEqual((got["destination"], got["destination_version"], got["destination_verified"]), ("ACH-SIM-NEWCO-0001", 2, 1))

    def test_a_restored_copy_without_write_authority_cannot_change_a_destination(self):
        d = tempfile.mkdtemp(prefix="cipher-payee-")
        self.addCleanup(shutil.rmtree, d, True)
        w = World(os.path.join(d, "live.sqlite"))
        self.addCleanup(w.c.db.close)
        ch = w.evidenced_change(NEW)
        ap = w.granted(ch["id"])
        copy = Cipher.open_restored(w.c.snapshot(os.path.join(d, "copy.sqlite")), provider=w.c.provider)
        self.addCleanup(copy.db.close)
        with self.assertRaises(WriteAuthorityError):
            copy.payments.request_destination_change(w.sid, OTHER, "ap-clerk", "new bank", "ap-clerk")
        with self.assertRaises(WriteAuthorityError):
            copy.execute(ap["id"], actor="bank-admin")
        self.assertEqual(copy.party(w.sid)["destination"], OLD)
        self.assertEqual(w.c.execute(ap["id"], actor="bank-admin").result["status"], "executed")  # the live workspace is unaffected


class GoldenFixtureTests(unittest.TestCase):
    def test_golden_numbers_are_unchanged_by_governed_destination_changes(self):
        c = Cipher()
        r = run_golden_fixture(c)
        self.assertEqual((r["bill1"]["amount_due"], r["bill2"]["amount_due"], r["prime"]["amount_due"]), ("27000.00", "18000.00", "54000.00"))
        self.assertEqual((r["executed_amount"], r["bank"], r["fees"], r["cost"], r["stored"]), ("122000.00", "-27005.00", "5.00", "45000.00", "5000.00"))
        self.assertEqual((r["payment"]["transfers"], r["payment"]["status"]), (1, "settled"))
        self.assertTrue(r["trial_balance"]["balanced"] and r["ap"]["reconciled"] and r["audit"]["ok"])
        supplier = c.party(c.payments.get(c.payments.list()[0]["id"])["party_id"])
        self.assertEqual(c.payments.change_history(supplier["id"]), [])  # the fixture seeds through the fixture path
        self.assertEqual(c.payments.list()[0]["lifecycle_status"], "settled")


if __name__ == "__main__":
    unittest.main()
