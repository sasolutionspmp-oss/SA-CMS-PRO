"""Commitment and supplier-bill controls: stored-material eligibility, the per-line cap,
retainage release after closeout, the 2050 / 1300 subledgers and journal-preview binding,
plus the hardening against double claims, approval replay, unapproved execution, raw
status edits, legacy billing-history ties and retainage-payment scoping.

Cost codes are original placeholders ("XX 10 00"), never real classification numbers."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from apps.cipher.core import db as core_db
from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import new_id, sha256_hex, utcnow_iso
from apps.cipher.core.money import MoneyError, fmt
from apps.cipher.domain.ap_intake import INTEGRITY_SCHEMA_NAME as AP_INTAKE_INTEGRITY_SCHEMA_NAME
from apps.cipher.domain.bills import (
    BILLS_HARDENING_SCHEMA_NAME, BILLS_LIFECYCLE_SCHEMA_NAME, BILLS_LINK_PAYMENT_SCHEMA_NAME, BILLS_SCHEMA_NAME, BillError, BillIneligible,
)
from apps.cipher.domain.commitments import COMMITMENTS_SCHEMA_NAME, CommitmentError
from apps.cipher.domain.ledger import LedgerError, PeriodNotOpen
from apps.cipher.domain.payments import PaymentError
from apps.cipher.service import Cipher, RoleNotAuthorised, run_golden_fixture

ENTITY = "S&A Solutions LLC (synthetic)"
# entries that build on bills_invoices_credits_corrections: a workspace older than it has none of them
AFTER_LIFECYCLE = (BILLS_LINK_PAYMENT_SCHEMA_NAME, AP_INTAKE_INTEGRITY_SCHEMA_NAME)


def lines_of(journal):
    return [(ln["account_code"], ln["debit"], ln["credit"]) for ln in journal["lines"]]


LOT_COLUMNS = ("id", "commitment_id", "sov_line_id", "description", "eligible_amount", "remaining_amount", "evidence_hash", "location", "created_at",
               "evidence_document_id", "evidence_revision_id")


def raw_lot(c, commitment_id, sov_line_id, amount, *, evidence_hash, location="Laydown yard A (synthetic)", document_id=None, revision_id=None, **extra):
    """A stored-material lot written with raw SQL, bypassing add_stored_material (a synthetic probe)."""
    lid = new_id("lot")
    cols = list(LOT_COLUMNS) + list(extra)
    vals = [lid, commitment_id, sov_line_id, "raw probe lot", amount, amount, evidence_hash, location, utcnow_iso(), document_id, revision_id] + list(extra.values())
    c.db.execute(f"INSERT INTO stored_material_lots ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(vals))
    return lid


def raw_journal(c, period_id, lines):
    """A balanced journal inserted with raw SQL, bypassing every posting path (a synthetic probe)."""
    jid = new_id("jrn")
    cols = ["id", "period_id", "posted_at", "description", "source_type", "source_id", "source_version", "rule_version", "approval_id", "reversal_of", "posted_by"]
    vals = [jid, period_id, utcnow_iso(), "synthetic probe written around the posting rules", "probe", jid, "1", "probe", None, None, "probe"]
    if "line_count" in {r["name"] for r in c.db.query("PRAGMA table_info(journals)")}:  # sealed journals declare their line count
        cols.append("line_count")
        vals.append(len(lines))
    with c.db.transaction() as conn:  # header and lines commit together (a journal is complete when it commits)
        conn.execute(f"INSERT INTO journals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(vals))
        for n, (account, debit, credit) in enumerate(lines, start=1):
            conn.execute(
                "INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, project_id, party_id, memo) VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id("jln"), jid, n, account, debit, credit, None, None, "probe"),
            )
    return jid


class World:
    """Verified subcontractor, project, open period and an executed 60,000 + 40,000 commitment at 10% retainage."""

    def __init__(self, path=":memory:"):
        c = self.c = Cipher(path)
        sup = c.add_party(kind="supplier", name="Synthetic sheet pile subcontractor", destination="ACH-SIM-BC-0001")
        self.supplier = c.verify_destination(sup["id"], destination="ACH-SIM-BC-0001", verified_by="owner")
        customer = c.add_party(kind="customer", name="Synthetic owner agency")
        self.project = c.create_project(name="Synthetic cofferdam and dewatering", entity=ENTITY, budget="150000", customer_id=customer["id"])
        self.pid = self.project["id"]
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.cid = self.commitment("60000", "40000")

    def commitment(self, *amounts, rate="0.10", supplier_id=None):
        cmt = self.c.commitments.create(
            project_id=self.pid, supplier_id=supplier_id or self.supplier["id"], title="Synthetic subcontract",
            sov_lines=[{"description": f"Scope {i}", "amount": a, "cost_code": f"XX {i}0 00"} for i, a in enumerate(amounts, start=1)],
            retainage_rate=rate, actor="pm",
        )
        self.c.approve_and_execute("commitment.execute", cmt["id"], actor_role="pm")
        return cmt["id"]

    def line(self, n, cid=None):
        return self.c.commitments.get(cid or self.cid)["sov"][n - 1]["id"]

    def evidence(self, label, project_id=None):
        doc = self.c.evidence.register_document(project_id=project_id or self.pid, kind="stored_material_evidence",
                                                title=f"{label}: bill of sale, insurance, laydown photos", actor="pm")
        rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic stored-material evidence rev 1: {label}".encode(), actor="pm")
        return doc, rev

    def revise(self, doc, label):
        return self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic stored-material evidence revised: {label}".encode(), actor="pm")

    def lot(self, label, amount, *, line_no=1, cid=None):
        doc, rev = self.evidence(label)
        lot = self.c.bills.add_stored_material(commitment_id=cid or self.cid, sov_line_id=self.line(line_no, cid), description=label,
                                               eligible_amount=amount, evidence_hash=rev["content_hash"], location="Laydown yard A (synthetic)", actor="pm")
        return lot, doc, rev

    def certify(self, installed, transfers=None, *, cid=None, period="P1"):
        return self.c.bills.certify(commitment_id=cid or self.cid, period_id=period,
                                    installed=[{"sov_line_id": self.line(n, cid), "cumulative_installed": v} for n, v in installed.items()],
                                    transfers=transfers, actor="pm")

    def post(self, bill_id):
        return self.c.approve_and_execute("bill.approve", bill_id, actor_role="accountant", actor="accountant")

    def assert_books(self, tc):
        c = self.c
        tc.assertTrue(c.ledger.trial_balance()["balanced"])
        tc.assertTrue(c.audit.verify_chain()["ok"])
        for rec in (c.bills.ap_open_items(), c.bills.retainage_open_items(), c.bills.stored_material_items(),
                    c.bills.retainage_open_items(self.pid), c.bills.stored_material_items(self.pid)):
            tc.assertTrue(rec["reconciled"], rec)


# --------------------------------------------------------------------------- #
# 1. stored-material eligibility                                               #
# --------------------------------------------------------------------------- #

class StoredMaterialEvidenceTests(unittest.TestCase):
    def test_evidence_must_be_the_current_revision_on_the_commitments_project(self):
        w = World()
        c = w.c
        doc, rev1 = w.evidence("ductile iron pipe")
        rev2 = w.revise(doc, "ductile iron pipe, insurance renewed")
        other = c.create_project(name="Another synthetic project", entity=ENTITY, budget="1000")
        _, other_rev = w.evidence("pipe on the other project", project_id=other["id"])
        line1 = w.line(1)

        def add(evidence_hash, location="Laydown yard A (synthetic)", **kw):
            return c.bills.add_stored_material(commitment_id=w.cid, sov_line_id=line1, description="Ductile iron pipe", eligible_amount="10000",
                                               evidence_hash=evidence_hash, location=location, actor="pm", **kw)

        for bad in (rev1["content_hash"],               # superseded revision of the right document
                    other_rev["content_hash"],          # current revision, but another project's document
                    sha256_hex(b"a hash Cipher never stored"),
                    ""):
            with self.assertRaises(BillError):
                add(bad)
        with self.assertRaises(BillError):  # no storage location
            add(rev2["content_hash"], location="   ")
        with self.assertRaises(BillError):  # a revision id that does not carry the hash
            add(rev2["content_hash"], evidence_revision_id=rev1["id"])
        self.assertEqual(c.bills.lots(w.cid), [])

        lot = add(rev2["content_hash"])
        self.assertEqual((lot["evidence_document_id"], lot["evidence_revision_id"], lot["evidence_hash"], lot["evidence_status"], lot["location"]),
                         (doc["id"], rev2["id"], rev2["content_hash"], "current", "Laydown yard A (synthetic)"))
        self.assertEqual((lot["eligibility_confirmation_required"], lot["frozen"], lot["billed"], lot["evidence_confirmed_by"]), (False, False, False, "pm"))
        added = [e for e in c.audit.entries(entity_type="stored_material_lot", entity_id=lot["id"]) if e["action"] == "stored_material.added"]
        self.assertEqual(len(added), 1)
        self.assertEqual(json.loads(added[0]["payload_json"])["evidence_revision_id"], rev2["id"])
        with self.assertRaises(BillError):  # the same evidence revision cannot support a second lot
            add(rev2["content_hash"])
        self.assertEqual(len(c.bills.lots(w.cid)), 1)
        w.assert_books(self)

    def test_revised_evidence_freezes_a_billed_lot_until_reconfirmed(self):
        w = World()
        c = w.c
        lot, doc, rev1 = w.lot("sheet piling", "10000")
        b1 = w.certify({1: "20000"})
        self.assertEqual((b1["cumulative_stored"], b1["cumulative_gross"], b1["amount_due"], b1["excluded_lots"]), ("10000.00", "30000.00", "27000.00", []))
        w.post(b1["id"])
        self.assertEqual(c.bills.lot(lot["id"])["billed_bill_id"], b1["id"])

        rev2 = w.revise(doc, "sheet piling: insurance certificate replaced")
        flagged = c.bills.lots(w.cid)[0]
        self.assertEqual((flagged["evidence_status"], flagged["eligibility_confirmation_required"], flagged["frozen"], flagged["evidence_current_revision_id"]),
                         ("superseded", True, True, rev2["id"]))
        self.assertEqual(c.bills.stored_material_items(w.pid)["items"][0]["lots_requiring_confirmation"], [lot["id"]])
        with self.assertRaises(BillError):  # a frozen lot cannot be transferred
            w.certify({1: "45000"}, transfers=[{"lot_id": lot["id"], "amount": "10000"}])
        self.assertEqual(c.bills.latest(w.cid)["id"], b1["id"])
        self.assertEqual(c.bills.lot(lot["id"])["remaining_amount"], "10000.00")

        with self.assertRaises(BillError):  # the superseded revision is not a confirmation
            c.bills.confirm_lot_evidence(lot["id"], rev1["content_hash"], "pm")
        with self.assertRaises(BillError):
            c.bills.confirm_lot_evidence(lot["id"], sha256_hex(b"unrelated"), "pm")
        confirmed = c.bills.confirm_lot_evidence(lot["id"], rev2["content_hash"], "pm")
        self.assertEqual((confirmed["evidence_revision_id"], confirmed["evidence_hash"], confirmed["evidence_status"], confirmed["frozen"]),
                         (rev2["id"], rev2["content_hash"], "current", False))
        with self.assertRaises(BillError):  # confirming twice is a duplicate
            c.bills.confirm_lot_evidence(lot["id"], rev2["content_hash"], "pm")
        self.assertEqual([e["action"] for e in c.audit.entries(entity_type="stored_material_lot", entity_id=lot["id"])],
                         ["stored_material.added", "stored_material.evidence_confirmed"])

        b2 = w.certify({1: "45000"}, transfers=[{"lot_id": lot["id"], "amount": "10000"}])
        self.assertEqual((b2["cumulative_installed"], b2["cumulative_stored"], b2["cumulative_gross"], b2["cumulative_retainage"], b2["amount_due"],
                          b2["retainage_this_period"], b2["stored_transferred_this_period"]),
                         ("45000.00", "0.00", "45000.00", "4500.00", "13500.00", "1500.00", "10000.00"))
        w.post(b2["id"])
        self.assertEqual([lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=b2["id"])], [
            [("5000", "10000.00", "0.00"), ("1300", "0.00", "10000.00")],
            [("5000", "15000.00", "0.00"), ("2000", "0.00", "13500.00"), ("2050", "0.00", "1500.00")],
        ])
        self.assertEqual((str(c.ledger.balance("1300")), str(c.ledger.balance("2050")), str(c.ledger.balance("5000"))), ("0.00", "4500.00", "45000.00"))
        w.assert_books(self)

    def test_never_billed_lot_with_revised_evidence_waits_for_confirmation(self):
        w = World()
        c = w.c
        lot, doc, _ = w.lot("dewatering pumps", "10000")
        rev2 = w.revise(doc, "dewatering pumps: delivery ticket corrected")
        b1 = w.certify({1: "20000"})
        self.assertEqual((b1["cumulative_stored"], b1["cumulative_gross"], b1["stored_added_this_period"]), ("0.00", "20000.00", "0.00"))
        self.assertEqual([x["lot_id"] for x in b1["excluded_lots"]], [lot["id"]])
        self.assertFalse(c.bills.lot(lot["id"])["billed"])
        w.post(b1["id"])
        self.assertEqual(str(c.ledger.balance("1300")), "0.00")

        c.bills.confirm_lot_evidence(lot["id"], rev2["content_hash"], "pm")
        b2 = w.certify({1: "20000"})  # no new installed work: the confirmed lot is newly billed as stored
        self.assertEqual((b2["cumulative_stored"], b2["stored_added_this_period"], b2["amount_due"], b2["retainage_this_period"], b2["excluded_lots"]),
                         ("10000.00", "10000.00", "9000.00", "1000.00", []))
        w.post(b2["id"])
        self.assertEqual(lines_of(c.ledger.journals(source_type="bill", source_id=b2["id"])[0]),
                         [("1300", "10000.00", "0.00"), ("2000", "0.00", "9000.00"), ("2050", "0.00", "1000.00")])
        self.assertEqual(c.bills.lot(lot["id"])["billed_bill_id"], b2["id"])
        w.assert_books(self)

    def test_draft_bill_approval_goes_stale_when_lot_evidence_is_revised(self):
        w = World()
        c = w.c
        lot, doc, _ = w.lot("valves", "5000")
        b = w.certify({1: "20000"})
        ap = c.request_approval("bill.approve", b["id"], actor_role="accountant")
        self.assertEqual(ap["manifest"]["bindings"]["stored_lots"], [{"lot_id": lot["id"], "evidence_revision_id": lot["evidence_revision_id"], "evidence_status": "current"}])
        c.approve(ap["id"], approver="controller", approver_role="controller")
        rev2 = w.revise(doc, "valves: title transferred to a different yard")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="accountant")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.ledger.journals(source_type="bill"), [])
        # a fresh approval sees the superseded evidence, and posting still refuses it
        ap2 = c.request_approval("bill.approve", b["id"], actor_role="accountant")
        c.approve(ap2["id"])
        with self.assertRaises(BillError):
            c.execute(ap2["id"], actor="accountant")
        c.reject(ap2["id"], reason="lot evidence must be re-confirmed")
        self.assertEqual(c.ledger.journals(source_type="bill"), [])
        self.assertEqual(c.bills.get(b["id"])["status"], "draft")
        # re-confirmed: a new approval binds the new revision and posts
        c.bills.confirm_lot_evidence(lot["id"], rev2["content_hash"], "pm")
        res = w.post(b["id"])
        self.assertEqual(c.approvals.get(c.bills.get(b["id"])["approval_id"])["manifest"]["bindings"]["stored_lots"][0]["evidence_revision_id"], rev2["id"])
        self.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])),
                         [("5000", "20000.00", "0.00"), ("1300", "5000.00", "0.00"), ("2000", "0.00", "22500.00"), ("2050", "0.00", "2500.00")])
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 2. per-line cap                                                              #
# --------------------------------------------------------------------------- #

class PerLineCapTests(unittest.TestCase):
    def test_certify_caps_installed_plus_stored_per_line(self):
        w = World()
        c = w.c
        w.lot("sheet piling", "10000", line_no=1)
        with self.assertRaises(BillError) as cm:  # 55,000 installed + 10,000 stored > line 1 (60,000)
            w.certify({1: "55000"})
        self.assertIn("SOV line 1", str(cm.exception))
        self.assertEqual(c.bills.list(commitment_id=w.cid), [])
        b = w.certify({1: "50000"})  # exactly the line value
        self.assertEqual((b["cumulative_installed"], b["cumulative_stored"], b["cumulative_gross"]), ("50000.00", "10000.00", "60000.00"))
        with self.assertRaises(BillError) as cm:  # line 2 is 40,000
            w.lot("pump skid", "40000.01", line_no=2)
        self.assertIn("SOV line 2", str(cm.exception))
        w.lot("pump skid (re-measured)", "40000", line_no=2)
        w.post(b["id"])
        with self.assertRaises(BillError) as cm:  # line 1 is full: 50,000 installed + 10,000 stored
            w.lot("extra pipe", "0.01", line_no=1)
        self.assertIn("SOV line 1", str(cm.exception))
        with self.assertRaises(BillError):  # installing more on line 1 without transferring the stored lot
            w.certify({1: "50000.01"})
        w.assert_books(self)

    def test_transfer_must_land_on_its_own_line(self):
        w = World()
        lot, _, _ = w.lot("sheet piling", "10000", line_no=1)
        with self.assertRaises(BillError) as cm:
            w.certify({2: "10000"}, transfers=[{"lot_id": lot["id"], "amount": "10000"}])
        self.assertIn("SOV line 1", str(cm.exception))
        self.assertEqual(w.c.bills.lot(lot["id"])["remaining_amount"], "10000.00")

    def test_deductive_change_cannot_cut_below_installed_and_stored(self):
        w = World()
        c = w.c
        w.lot("sheet piling", "10000", line_no=1)
        w.post(w.certify({1: "40000"})["id"])  # line 1 carries 40,000 installed + 10,000 stored
        too_deep = c.commitments.propose_change(w.cid, amount="-15000", reason="descope (synthetic)", sov_line_id=w.line(1), actor="pm")
        with self.assertRaises(CommitmentError):
            c.request_approval("change.execute", too_deep["id"], actor_role="pm")
        self.assertEqual(c.commitments.get(w.cid)["sov"][0]["amount"], "60000.00")
        c.commitments.reject_change(too_deep["id"], actor="pm", reason="would cut below billed value")
        with self.assertRaises(CommitmentError):  # rejecting twice is a duplicate
            c.commitments.reject_change(too_deep["id"], actor="pm", reason="again")
        ok =c.commitments.propose_change(w.cid, amount="-10000", reason="descope (synthetic)", sov_line_id=w.line(1), actor="pm")
        c.approve_and_execute("change.execute", ok["id"], actor_role="pm")
        cmt = c.commitments.get(w.cid)
        self.assertEqual((cmt["sov"][0]["amount"], cmt["executed_amount"]), ("50000.00", "90000.00"))
        with self.assertRaises(BillError):  # the line is now exactly full
            w.lot("more piling", "1", line_no=1)
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 3. retainage release after closeout                                          #
# --------------------------------------------------------------------------- #

class RetainageReleaseTests(unittest.TestCase):
    def full_bill(self, w):
        w.post(w.certify({1: "60000", 2: "40000"})["id"])
        self.assertEqual(str(w.c.ledger.balance("2050")), "10000.00")

    def test_release_refused_before_close_and_allowed_after(self):
        w = World()
        c = w.c
        self.full_bill(w)
        with self.assertRaises(BillError):
            c.request_approval("retainage.release", w.cid, actor_role="accountant")
        with self.assertRaises(BillError):
            c.approve_and_execute("retainage.release", w.cid, actor_role="accountant", period_id="P1")
        with self.assertRaises(BillError) as cm:  # the posting path re-checks the commitment status itself
            c.bills.release_retainage(commitment_id=w.cid, period_id="P1", approval_id="apr_not_a_real_approval", actor="accountant")
        self.assertIn("not closed", str(cm.exception))
        self.assertEqual(c.ledger.journals(source_type="retainage_release"), [])
        self.assertEqual([a for a in c.approvals.list() if a["operation"] == "retainage.release"], [])  # refused before any approval existed

        c.commitments.close(w.cid, actor="pm")
        res = c.approve_and_execute("retainage.release", w.cid, actor_role="accountant", actor="accountant", period_id="P1")
        self.assertEqual(res.result["amount"], "10000.00")
        self.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])), [("2050", "10000.00", "0.00"), ("2000", "0.00", "10000.00")])
        ret = c.bills.retainage_open_items(w.pid)
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("0.00", "0.00", True))
        self.assertEqual(ret["items"], [{"commitment_id": w.cid, "project_id": w.pid, "supplier_id": w.supplier["id"], "commitment_status": "closed",
                                         "retained": "10000.00", "released": "10000.00", "held": "0.00"}])
        ap = c.bills.ap_open_items(w.pid)
        self.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("100000.00", "100000.00", True))
        with self.assertRaises(BillError):  # released exactly once
            c.approve_and_execute("retainage.release", w.cid, actor_role="accountant", period_id="P1")
        self.assertEqual(len(c.ledger.journals(source_type="retainage_release")), 1)
        w.assert_books(self)

    def test_manifest_binds_status_version_entity_and_the_release_rechecks(self):
        w = World()
        c = w.c
        self.full_bill(w)
        c.commitments.close(w.cid, actor="pm")
        cmt = c.commitments.get(w.cid)
        ap = c.request_approval("retainage.release", w.cid, actor_role="accountant")
        m = ap["manifest"]
        self.assertEqual(m["amounts"], {"retainage_held": "10000.00"})
        self.assertEqual((m["bindings"]["commitment_status"], m["bindings"]["commitment_version"], m["entity"], m["currency"]),
                         ("closed", cmt["version"], ENTITY, "USD"))
        with self.assertRaises(BillError):  # an approval that was never consumed cannot drive the posting
            c.bills.release_retainage(commitment_id=w.cid, period_id="P1", approval_id=ap["id"], actor="accountant")
        c.approve(ap["id"], approver="controller", approver_role="controller")
        # the project's legal entity changes after the grant: the approval is stale
        c.db.execute("UPDATE projects SET entity=? WHERE id=?", ("Another legal entity (synthetic)", w.pid))
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.ledger.journals(source_type="retainage_release"), [])
        c.db.execute("UPDATE projects SET entity=? WHERE id=?", (ENTITY, w.pid))

        # closed period: refused, nothing posted; the open period takes it
        ap2 = c.request_approval("retainage.release", w.cid, actor_role="treasury")
        c.approve(ap2["id"])
        c.close_period("P1")
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        with self.assertRaises(PeriodNotOpen):
            c.execute(ap2["id"], actor="treasury", period_id="P1")
        self.assertEqual(c.ledger.journals(source_type="retainage_release"), [])
        res = c.execute(ap2["id"], actor="treasury", period_id="P2")
        self.assertEqual((c.ledger.journal(res.result["journal_id"])["period_id"], res.result["amount"]), ("P2", "10000.00"))
        w.assert_books(self)

    def test_release_is_per_commitment(self):
        w = World()
        c = w.c
        second = w.commitment("50000")  # same supplier, same project
        w.post(w.certify({1: "30000"})["id"])
        w.post(w.certify({1: "20000"}, cid=second)["id"])
        self.assertEqual(str(c.ledger.balance("2050")), "5000.00")
        c.commitments.close(w.cid, actor="pm")
        res = c.approve_and_execute("retainage.release", w.cid, actor_role="accountant", period_id="P1")
        self.assertEqual(res.result["amount"], "3000.00")  # never the other commitment's 2,000
        self.assertEqual(str(c.ledger.balance("2050")), "2000.00")
        held = {i["commitment_id"]: i["held"] for i in c.bills.retainage_open_items()["items"]}
        self.assertEqual(held, {w.cid: "0.00", second: "2000.00"})
        with self.assertRaises(BillError):
            c.approve_and_execute("retainage.release", second, actor_role="accountant", period_id="P1")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 4. retainage payable and stored-material subledgers                         #
# --------------------------------------------------------------------------- #

class SubledgerTests(unittest.TestCase):
    def test_golden_fixture_retainage_and_stored_subledgers_reconcile(self):
        c = Cipher()
        r = run_golden_fixture(c)
        for scope in (None, r["project_id"]):
            ret = c.bills.retainage_open_items(scope)
            self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("5000.00", "5000.00", True))
            st = c.bills.stored_material_items(scope)
            self.assertEqual((st["subledger_total"], st["control_balance"], st["reconciled"]), ("5000.00", "5000.00", True))
        ret_items = c.bills.retainage_open_items()["items"]
        self.assertEqual([(i["commitment_id"], i["retained"], i["released"], i["held"]) for i in ret_items], [(r["commitment_id"], "5000.00", "0.00", "5000.00")])
        st_items = c.bills.stored_material_items()["items"]
        self.assertEqual([(i["commitment_id"], i["sequence"], i["stored"], i["lots_requiring_confirmation"]) for i in st_items],
                         [(r["commitment_id"], 2, "5000.00", [])])
        checks = {chk["check"]: chk["ok"] for chk in c.plugin("core_reconciliation").close_checks("2026-11")}
        self.assertTrue(checks["retainage payable reconciled (2050)"])
        self.assertTrue(checks["stored materials reconciled (1300)"])
        export = c.audit_export()
        self.assertTrue(export["reconciliations"]["retainage payable reconciled (2050)"]["reconciled"])
        self.assertTrue(export["reconciliations"]["stored materials reconciled (1300)"]["reconciled"])

        # a posted bill, the source record of these subledgers, cannot be edited underneath them
        bill2 = next(b for b in c.bills.list(commitment_id=r["commitment_id"]) if b["sequence"] == 2)
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("UPDATE bills SET retainage_this_period='2001.00' WHERE id=?", (bill2["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("DELETE FROM bill_transfers WHERE bill_id=?", (bill2["id"],))
        self.assertEqual(c.bills.get(bill2["id"])["retainage_this_period"], "2000.00")

        # the subledgers derive from the bills, not from the ledger: a journal written around the
        # posting rules straight into the control accounts is exposed instead of absorbed
        raw_journal(c, "2026-11", [("5000", "1.00", "0.00"), ("2050", "0.00", "1.00"), ("1300", "2.00", "0.00"), ("5000", "0.00", "2.00")])
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        ret = c.bills.retainage_open_items()
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("5000.00", "5001.00", False))
        st = c.bills.stored_material_items()
        self.assertEqual((st["subledger_total"], st["control_balance"], st["reconciled"]), ("5000.00", "5002.00", False))
        self.assertTrue(c.bills.retainage_open_items(r["project_id"])["reconciled"])  # the probe carries no project
        checks = {chk["check"]: chk["ok"] for chk in c.plugin("core_reconciliation").close_checks("2026-11")}
        self.assertFalse(checks["retainage payable reconciled (2050)"])
        self.assertFalse(checks["stored materials reconciled (1300)"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_draft_bills_do_not_move_the_subledgers(self):
        w = World()
        c = w.c
        lot, _, _ = w.lot("sheet piling", "10000")
        w.post(w.certify({1: "20000"})["id"])
        draft = w.certify({1: "35000"}, transfers=[{"lot_id": lot["id"], "amount": "10000"}])
        self.assertEqual(c.bills.lot(lot["id"])["remaining_amount"], "0.00")  # the draft holds the transfer
        st = c.bills.stored_material_items(w.pid)
        self.assertEqual((st["subledger_total"], st["control_balance"], st["reconciled"]), ("10000.00", "10000.00", True))
        ret = c.bills.retainage_open_items(w.pid)
        self.assertEqual((ret["subledger_total"], ret["control_balance"], ret["reconciled"]), ("3000.00", "3000.00", True))
        c.bills.void(draft["id"], actor="pm", reason="re-measure")
        self.assertEqual(c.bills.lot(lot["id"])["remaining_amount"], "10000.00")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 5. manifests and the journal preview                                         #
# --------------------------------------------------------------------------- #

class JournalPreviewTests(unittest.TestCase):
    def granted_bill_approval(self, w):
        w.lot("sheet piling", "10000")
        b = w.certify({1: "20000"})
        ap = w.c.request_approval("bill.approve", b["id"], actor_role="accountant")
        w.c.approve(ap["id"], approver="controller", approver_role="controller")
        return b, ap

    def test_changed_retainage_rate_after_grant_invalidates(self):
        w = World()
        c = w.c
        b, ap = self.granted_bill_approval(w)
        self.assertEqual(ap["manifest"]["bindings"]["retainage_rate"], "0.100000")
        self.assertIn(("2050", "0.00", "3000.00"), [(ln["account"], ln["debit"], ln["credit"]) for ln in ap["manifest"]["bindings"]["journal_preview"][0]["lines"]])
        c.db.execute("UPDATE commitments SET retainage_rate='0.050000' WHERE id=?", (w.cid,))  # a silent edit; the version is untouched
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="accountant")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.ledger.journals(source_type="bill"), [])
        bill = c.bills.get(b["id"])
        self.assertTrue(bill["stale"])
        self.assertIn("retainage rate changed", bill["stale_reasons"])
        with self.assertRaises(BillError):  # even a fresh approval cannot post a bill priced at the old rate
            w.post(b["id"])
        self.assertEqual(c.ledger.journals(source_type="bill"), [])
        # void and re-certify: the preview follows the current rate
        c.bills.void(b["id"], actor="pm", reason="retainage rate corrected")
        b2 = w.certify({1: "20000"})
        self.assertEqual((b2["cumulative_retainage"], b2["amount_due"]), ("1500.00", "28500.00"))
        res = w.post(b2["id"])
        self.assertEqual(lines_of(c.ledger.journal(res.result["journal_id"])),
                         [("5000", "20000.00", "0.00"), ("1300", "10000.00", "0.00"), ("2000", "0.00", "28500.00"), ("2050", "0.00", "1500.00")])
        w.assert_books(self)

    def test_changed_sov_after_grant_invalidates(self):
        w = World()
        c = w.c
        b, ap = self.granted_bill_approval(w)
        c.db.execute("UPDATE sov_lines SET description=? WHERE id=?", ("Scope 1 (edited silently)", w.line(1)))
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="accountant")
        self.assertEqual(c.ledger.journals(source_type="bill"), [])
        self.assertIn("schedule of values changed", c.bills.get(b["id"])["stale_reasons"])
        c.db.execute("UPDATE sov_lines SET description=? WHERE id=?", ("Scope 1", w.line(1)))
        self.assertFalse(c.bills.get(b["id"])["stale"])
        # an executed change on the SOV invalidates an open approval the regular way
        ap2 = c.request_approval("bill.approve", b["id"], actor_role="accountant")
        c.approve(ap2["id"])
        ch = c.commitments.propose_change(w.cid, amount="5000", reason="added sheet piling (synthetic)", sov_line_id=w.line(2), actor="pm")
        c.approve_and_execute("change.execute", ch["id"], actor_role="pm")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            c.execute(ap2["id"], actor="accountant")
        self.assertEqual(c.ledger.journals(source_type="bill"), [])
        w.assert_books(self)

    def test_posting_never_differs_from_the_approved_preview(self):
        w = World()
        c = w.c
        b, ap = self.granted_bill_approval(w)
        approved_preview = ap["manifest"]["bindings"]["journal_preview"]
        original_post = c.bills.post

        def tampering_post(bill_id, *, approval_id, actor):
            # simulate the bill's figures changing between consumption and posting
            c.db.execute("UPDATE bills SET amount_due='26000.00', retainage_this_period='4000.00' WHERE id=?", (bill_id,))
            return original_post(bill_id, approval_id=approval_id, actor=actor)

        c.bills.post = tampering_post
        with self.assertRaises(BillError) as cm:
            c.execute(ap["id"], actor="accountant")
        self.assertIn("journal preview", str(cm.exception))
        c.bills.post = original_post
        self.assertEqual(c.ledger.journals(source_type="bill"), [])
        self.assertEqual((c.bills.get(b["id"])["amount_due"], c.approvals.get(ap["id"])["status"]), ("27000.00", "granted"))  # rolled back
        # a consumed approval for another subject cannot post this bill either
        with self.assertRaises(BillError):
            c.bills.post(b["id"], approval_id=c.commitments.get(w.cid)["approval_id"], actor="accountant")
        res = c.execute(ap["id"], actor="accountant")
        posted = c.ledger.journal(res.result["journal_id"])
        self.assertEqual([{"account": ln["account_code"], "debit": ln["debit"], "credit": ln["credit"], "project_id": ln["project_id"],
                           "party_id": ln["party_id"], "memo": ln["memo"]} for ln in posted["lines"]], approved_preview[0]["lines"])
        self.assertEqual((posted["period_id"], posted["approval_id"]), (approved_preview[0]["period_id"], ap["id"]))
        w.assert_books(self)

    def test_commitment_and_change_approvals_bind_entity_and_currency(self):
        w = World()
        c = w.c
        cmt = c.commitments.create(project_id=w.pid, supplier_id=w.supplier["id"], title="Draft subcontract",
                                   sov_lines=[{"description": "Dewatering wells", "amount": "8000", "cost_code": "XX 30 00"}], actor="pm")
        ap = c.request_approval("commitment.execute", cmt["id"], actor_role="pm")
        self.assertEqual((ap["manifest"]["entity"], ap["manifest"]["currency"]), (ENTITY, "USD"))
        c.approve(ap["id"], approver="pm", approver_role="pm")
        c.db.execute("UPDATE projects SET currency='CAD' WHERE id=?", (w.pid,))
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="pm")
        self.assertEqual(c.commitments.get(cmt["id"])["status"], "draft")
        c.db.execute("UPDATE projects SET currency='USD' WHERE id=?", (w.pid,))
        ch = c.commitments.propose_change(w.cid, amount="2500", reason="extra wellpoints (synthetic)", sov_line_id=w.line(1), actor="pm")
        chm = c.request_approval("change.execute", ch["id"], actor_role="pm")
        self.assertEqual((chm["manifest"]["entity"], chm["manifest"]["currency"], chm["manifest"]["bindings"]["change_status"]), (ENTITY, "USD", "pending"))
        c.approve(chm["id"])
        dup = c.request_approval("change.execute", ch["id"], actor_role="pm")
        c.approve(dup["id"])
        c.execute(chm["id"], actor="pm")
        with self.assertRaises(StaleApprovalError):  # the same change cannot execute twice
            c.execute(dup["id"], actor="pm")
        self.assertEqual(c.commitments.get(w.cid)["executed_amount"], "102500.00")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 6. invalid input, closed periods and storage-level guards                    #
# --------------------------------------------------------------------------- #

class InvalidInputTests(unittest.TestCase):
    def test_invalid_input_is_refused(self):
        w = World()
        c = w.c
        _, rev = w.evidence("sheet piling")
        line1 = w.line(1)

        def add(amount="1000", line=line1, cid=None, description="Sheet piling"):
            return c.bills.add_stored_material(commitment_id=cid or w.cid, sov_line_id=line, description=description, eligible_amount=amount,
                                               evidence_hash=rev["content_hash"], location="Laydown yard A (synthetic)", actor="pm")

        with self.assertRaises(MoneyError):
            add(amount=1000.0)
        for bad in ("0", "-5"):
            with self.assertRaises(BillError):
                add(amount=bad)
        with self.assertRaises(BillError):
            add(description="  ")
        other = w.commitment("1000")
        with self.assertRaises(BillError):  # a line of another commitment
            add(line=w.line(1, other))
        draft = c.commitments.create(project_id=w.pid, supplier_id=w.supplier["id"], title="Draft", sov_lines=[{"description": "x", "amount": "1000"}], actor="pm")
        with self.assertRaises(BillError):
            add(cid=draft["id"], line=c.commitments.get(draft["id"])["sov"][0]["id"])
        with self.assertRaises(BillError):
            c.bills.confirm_lot_evidence("lot_unknown", rev["content_hash"], "pm")
        with self.assertRaises(BillError):
            c.bills.certify(commitment_id=w.cid, period_id="P1", installed=[{"sov_line_id": line1, "cumulative_installed": "1"}, {"sov_line_id": line1, "cumulative_installed": "2"}], actor="pm")
        with self.assertRaises(BillError):
            c.bills.certify(commitment_id=w.cid, period_id="P1", installed=[{"sov_line_id": line1}], actor="pm")
        with self.assertRaises(BillError):
            c.bills.certify(commitment_id=w.cid, period_id="P1", installed="20000", actor="pm")
        with self.assertRaises(CommitmentError):
            c.commitments.propose_change(w.cid, amount="0", reason="nothing", sov_line_id=line1, actor="pm")
        w.post(w.certify({1: "20000"})["id"])
        with self.assertRaises(BillError):  # nothing new since the previous bill
            w.certify({1: "20000"})
        c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            w.certify({1: "30000"})
        self.assertEqual(len(c.bills.list(commitment_id=w.cid)), 1)
        w.assert_books(self)

    def test_schema_entry_and_storage_guards(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "bills-controls.sqlite")
        w = World(path)
        c = w.c
        lot, _, rev = w.lot("sheet piling", "10000")
        status = {v["name"]: v for v in c.db.schema_status()["versions"]}
        for name in (BILLS_SCHEMA_NAME, BILLS_HARDENING_SCHEMA_NAME, COMMITMENTS_SCHEMA_NAME):
            self.assertTrue(status[name]["applied"], name)
            self.assertTrue(status[name]["checksum_matches"], name)
        with self.assertRaises(sqlite3.DatabaseError):  # a lot's eligible amount is immutable
            c.db.execute("UPDATE stored_material_lots SET eligible_amount='99999.00' WHERE id=?", (lot["id"],))
        with self.assertRaises(sqlite3.IntegrityError):  # one lot per evidence revision, at the storage level too
            c.db.execute(
                """INSERT INTO stored_material_lots (id, commitment_id, sov_line_id, description, eligible_amount, remaining_amount, evidence_hash, location,
                   created_at, evidence_document_id, evidence_revision_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id("lot"), w.cid, w.line(2), "copy", "1.00", "1.00", rev["content_hash"], "yard", utcnow_iso(), lot["evidence_document_id"], rev["id"]),
            )
        c.db.close()
        reopened = Cipher(path)
        try:
            again = reopened.bills.lot(lot["id"])
            self.assertEqual((again["evidence_revision_id"], again["evidence_status"], again["remaining_amount"]), (rev["id"], "current", "10000.00"))
            self.assertEqual(reopened.db.migrate(), [])  # applied once; nothing pending
            self.assertTrue(reopened.audit.verify_chain()["ok"])
        finally:
            reopened.db.close()


# --------------------------------------------------------------------------- #
# 7. hardening: double claims, evidence kind                                  #
# --------------------------------------------------------------------------- #

class DoubleClaimTests(unittest.TestCase):
    def add(self, w, evidence_hash, amount="10000", line_no=1, **kw):
        return w.c.bills.add_stored_material(commitment_id=w.cid, sov_line_id=w.line(line_no), description="claimed again", eligible_amount=amount,
                                             evidence_hash=evidence_hash, location="Laydown yard A (synthetic)", actor="pm", **kw)

    def test_a_new_revision_of_claimed_evidence_never_backs_a_second_lot(self):
        w = World()
        c = w.c
        lot_a, doc, _ = w.lot("sheet piling delivery", "10000")
        w.post(w.certify({1: "20000"})["id"])
        self.assertEqual(str(c.ledger.balance("1300")), "10000.00")
        rev2 = w.revise(doc, "sheet piling delivery: delivery ticket reissued")
        with self.assertRaises(BillError) as cm:  # the same delivery document cannot back a second 10,000
            self.add(w, rev2["content_hash"])
        self.assertIn(lot_a["id"], str(cm.exception))
        with self.assertRaises(sqlite3.IntegrityError):  # nor at the storage level
            raw_lot(c, w.cid, w.line(1), "10000.00", evidence_hash=rev2["content_hash"], document_id=doc["id"], revision_id=rev2["id"])
        self.assertEqual([l["id"] for l in c.bills.lots(w.cid)], [lot_a["id"]])
        self.assertEqual(c.bills.latest(w.cid)["cumulative_stored"], "10000.00")

        # the new revision re-confirms the original lot, which then transfers normally
        confirmed = c.bills.confirm_lot_evidence(lot_a["id"], rev2["content_hash"], "pm")
        self.assertEqual((confirmed["evidence_revision_id"], confirmed["evidence_status"], confirmed["frozen"]), (rev2["id"], "current", False))
        b2 = w.certify({1: "35000"}, transfers=[{"lot_id": lot_a["id"], "amount": "10000"}])
        self.assertEqual((b2["cumulative_stored"], b2["stored_added_this_period"], b2["stored_transferred_this_period"], b2["amount_due"], b2["retainage_this_period"]),
                         ("0.00", "0.00", "10000.00", "4500.00", "500.00"))
        w.post(b2["id"])
        self.assertEqual([lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=b2["id"])], [
            [("5000", "10000.00", "0.00"), ("1300", "0.00", "10000.00")],
            [("5000", "5000.00", "0.00"), ("2000", "0.00", "4500.00"), ("2050", "0.00", "500.00")],
        ])
        self.assertEqual(str(c.ledger.balance("1300")), "0.00")
        # fully transferred, the document still never backs another lot
        rev3 = w.revise(doc, "sheet piling delivery: third copy")
        with self.assertRaises(BillError):
            self.add(w, rev3["content_hash"], amount="5000")
        self.assertEqual(len(c.bills.lots(w.cid)), 1)
        w.assert_books(self)

    def test_identical_evidence_content_on_a_twin_document_backs_one_lot(self):
        w = World()
        c = w.c
        content = b"synthetic stored-material evidence: one delivery of dewatering pumps"
        docs = [c.evidence.register_document(project_id=w.pid, kind="stored_material_evidence", title=f"Pumps evidence copy {n}", actor="pm") for n in (1, 2)]
        revs = [c.evidence.add_revision(document_id=d["id"], content=content, actor="pm") for d in docs]
        self.assertEqual(revs[0]["content_hash"], revs[1]["content_hash"])
        with self.assertRaises(BillError):  # ambiguous: the bare hash names two documents
            self.add(w, revs[0]["content_hash"], amount="8000", line_no=2)
        lot = self.add(w, revs[0]["content_hash"], amount="8000", line_no=2, evidence_revision_id=revs[0]["id"])
        with self.assertRaises(BillError) as cm:  # the same bytes on the twin document are the same material
            self.add(w, revs[1]["content_hash"], amount="8000", line_no=2, evidence_revision_id=revs[1]["id"])
        self.assertIn(lot["id"], str(cm.exception))
        with self.assertRaises(BillError):
            self.add(w, revs[1]["content_hash"], amount="8000", line_no=2)
        with self.assertRaises(sqlite3.IntegrityError):
            raw_lot(c, w.cid, w.line(2), "8000.00", evidence_hash=revs[1]["content_hash"], document_id=docs[1]["id"], revision_id=revs[1]["id"])
        self.assertEqual(len(c.bills.lots(w.cid)), 1)
        b = w.certify({2: "10000"})
        self.assertEqual((b["cumulative_stored"], b["cumulative_gross"]), ("8000.00", "18000.00"))
        w.post(b["id"])
        self.assertEqual(str(c.ledger.balance("1300")), "8000.00")
        w.assert_books(self)

    def test_only_stored_material_evidence_documents_qualify(self):
        w = World()
        c = w.c
        drawing = c.evidence.register_document(project_id=w.pid, kind="drawing", title="Cofferdam sheet pile layout", actor="pm")
        drev = c.evidence.add_revision(document_id=drawing["id"], content=b"synthetic drawing: sheet pile layout rev 1", actor="pm")
        with self.assertRaises(BillError) as cm:
            self.add(w, drev["content_hash"])
        self.assertIn("stored_material_evidence", str(cm.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            raw_lot(c, w.cid, w.line(1), "10000.00", evidence_hash=drev["content_hash"], document_id=drawing["id"], revision_id=drev["id"])

        # a lot recorded before evidence binding (unbound, no location) is frozen until confirmed against real evidence
        legacy = raw_lot(c, w.cid, w.line(1), "5000.00", evidence_hash="legacy-free-text-evidence", location="")
        lot = c.bills.lot(legacy)
        self.assertEqual((lot["evidence_status"], lot["frozen"], lot["eligibility_confirmation_required"]), ("unbound", True, True))
        with self.assertRaises(BillError):  # a drawing is not stored-material evidence
            c.bills.confirm_lot_evidence(legacy, drev["content_hash"], "pm", location="Laydown yard B (synthetic)")
        _, ev = w.evidence("legacy pipe")
        with self.assertRaises(BillError):  # the lot has no storage location on record
            c.bills.confirm_lot_evidence(legacy, ev["content_hash"], "pm")
        confirmed = c.bills.confirm_lot_evidence(legacy, ev["content_hash"], "pm", location="Laydown yard B (synthetic)")
        self.assertEqual((confirmed["evidence_status"], confirmed["evidence_revision_id"], confirmed["location"], confirmed["frozen"]),
                         ("current", ev["id"], "Laydown yard B (synthetic)", False))
        b = w.certify({1: "20000"})
        self.assertEqual((b["cumulative_stored"], b["amount_due"]), ("5000.00", "22500.00"))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 8. hardening: an approval takes effect once, and only its own               #
# --------------------------------------------------------------------------- #

class ApprovalEffectTests(unittest.TestCase):
    def test_consumed_release_approval_is_not_replayed_after_the_release_is_reversed(self):
        w = World()
        c = w.c
        w.post(w.certify({1: "60000", 2: "40000"})["id"])
        c.commitments.close(w.cid, actor="pm")
        ap = c.request_approval("retainage.release", w.cid, actor_role="accountant")
        c.approve(ap["id"], approver="controller", approver_role="controller")
        res = c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(res.result["amount"], "10000.00")
        c.ledger.reverse(res.result["journal_id"], period_id="P1", posted_by="controller", reason="release posted in error (synthetic)")
        self.assertEqual((str(c.bills.retainage_held(w.cid)), str(c.ledger.balance("2050"))), ("10000.00", "10000.00"))

        with self.assertRaises(BillError) as cm:  # the consumed approval already took effect once
            c.bills.release_retainage(commitment_id=w.cid, period_id="P1", approval_id=ap["id"], actor="accountant")
        self.assertIn("already took effect", str(cm.exception))
        self.assertEqual([j["approval_id"] for j in c.ledger.journals(source_type="retainage_release")], [ap["id"], None])
        self.assertTrue(c.execute(ap["id"], actor="accountant", period_id="P1").replayed)  # the service replays, posting nothing
        self.assertEqual(len(c.ledger.journals(source_type="retainage_release")), 2)
        self.assertEqual(str(c.ledger.balance("2050")), "10000.00")
        # a new human approval releases it again
        again = c.approve_and_execute("retainage.release", w.cid, actor_role="accountant", actor="accountant", period_id="P1")
        self.assertEqual(again.result["amount"], "10000.00")
        self.assertEqual((str(c.ledger.balance("2050")), str(c.ledger.balance("2000"))), ("0.00", "100000.00"))
        w.assert_books(self)

    def test_posted_bill_approval_never_posts_again(self):
        w = World()
        c = w.c
        b1 = w.certify({1: "20000"})
        res = w.post(b1["id"])
        used = c.bills.get(b1["id"])["approval_id"]
        b2 = w.certify({1: "30000"})
        with self.assertRaises(BillError):  # another bill's consumed approval
            c.bills.post(b2["id"], approval_id=used, actor="accountant")
        self.assertEqual(c.bills.get(b2["id"])["status"], "draft")
        self.assertEqual(len(c.ledger.journals(source_type="bill")), 1)
        self.assertEqual(res.result["journal_id"], c.bills.get(b1["id"])["journal_id"])
        w.assert_books(self)

    def test_commitment_and_change_execution_require_their_own_consumed_approval(self):
        w = World()
        c = w.c
        draft = c.commitments.create(project_id=w.pid, supplier_id=w.supplier["id"], title="Synthetic wellpoint subcontract",
                                     sov_lines=[{"description": "Wellpoint dewatering", "amount": "8000", "cost_code": "XX 40 00"}], actor="pm")
        other_consumed = c.commitments.get(w.cid)["approval_id"]
        for bad in (None, "", other_consumed, "apr_not_a_real_approval"):
            with self.subTest(approval=bad), self.assertRaises(CommitmentError):
                c.commitments.execute(draft["id"], approval_id=bad, actor="pm")
        ap = c.request_approval("commitment.execute", draft["id"], actor_role="pm")
        with self.assertRaises(CommitmentError):  # pending, not consumed
            c.commitments.execute(draft["id"], approval_id=ap["id"], actor="pm")
        c.approve(ap["id"], approver="pm", approver_role="pm")
        with self.assertRaises(CommitmentError):  # granted, still not consumed
            c.commitments.execute(draft["id"], approval_id=ap["id"], actor="pm")
        c.approvals.consume(ap["id"], current_manifest=c.commitments.manifest(draft["id"], actor_role="pm"), consumer="pm")
        c.db.execute("UPDATE sov_lines SET amount='9000.00' WHERE commitment_id=?", (draft["id"],))  # silent edit after consumption
        with self.assertRaises(CommitmentError) as cm:
            c.commitments.execute(draft["id"], approval_id=ap["id"], actor="pm")
        self.assertIn("changed after it was approved", str(cm.exception))
        self.assertEqual(c.commitments.get(draft["id"])["status"], "draft")
        c.db.execute("UPDATE sov_lines SET amount='8000.00' WHERE commitment_id=?", (draft["id"],))
        done = c.commitments.execute(draft["id"], approval_id=ap["id"], actor="pm")  # its own consumed approval, facts unchanged
        self.assertEqual((done["status"], done["executed_amount"], done["approval_id"]), ("executed", "8000.00", ap["id"]))

        big = c.commitments.propose_change(w.cid, amount="99999", reason="unapproved scope (synthetic)", sov_line_id=w.line(1), actor="pm")
        for bad in (None, ap["id"], "apr_not_a_real_approval"):
            with self.subTest(change_approval=bad), self.assertRaises(CommitmentError):
                c.commitments.execute_change(big["id"], approval_id=bad, actor="pm")
        small = c.commitments.propose_change(w.cid, amount="2500", reason="extra wellpoints (synthetic)", sov_line_id=w.line(1), actor="pm")
        c.approve_and_execute("change.execute", small["id"], actor_role="pm")
        with self.assertRaises(CommitmentError):  # another change's consumed approval
            c.commitments.execute_change(big["id"], approval_id=c.commitments.change(small["id"])["approval_id"], actor="pm")
        cmt = c.commitments.get(w.cid)
        self.assertEqual((cmt["executed_amount"], cmt["sov"][0]["amount"], c.commitments.change(big["id"])["status"]), ("102500.00", "62500.00", "pending"))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 9. hardening: frozen lots and the per-line cap, withdrawal                  #
# --------------------------------------------------------------------------- #

class FrozenLotCapTests(unittest.TestCase):
    def test_frozen_never_billed_lot_counts_against_the_line_and_can_be_withdrawn(self):
        w = World()
        c = w.c
        lot, doc, _ = w.lot("sheet piling", "10000", line_no=1)
        w.revise(doc, "sheet piling: insurance certificate lapsed")
        self.assertTrue(c.bills.lot(lot["id"])["frozen"])
        with self.assertRaises(BillError) as cm:  # 55,000 installed + 10,000 still stored on line 1 > 60,000
            w.certify({1: "55000"})
        self.assertIn("SOV line 1", str(cm.exception))
        self.assertIn("awaiting evidence confirmation", str(cm.exception))
        self.assertEqual(c.bills.list(commitment_id=w.cid), [])
        b1 = w.certify({1: "50000"})  # left out of the bill, the lot still holds its place on the line
        self.assertEqual((b1["cumulative_stored"], b1["amount_due"], [x["lot_id"] for x in b1["excluded_lots"]]), ("0.00", "45000.00", [lot["id"]]))
        w.post(b1["id"])

        for actor, reason in (("pm", "  "), ("", "material left the site")):
            with self.assertRaises(BillError):
                c.bills.withdraw_stored_material(lot["id"], actor=actor, reason=reason)
        gone = c.bills.withdraw_stored_material(lot["id"], actor="pm", reason="material left the site; insurance lapsed (synthetic)")
        self.assertEqual((gone["withdrawn"], gone["remaining_amount"], gone["eligible_amount"], gone["frozen"], gone["withdrawn_by"]),
                         (True, "0.00", "10000.00", False, "pm"))
        with self.assertRaises(BillError):  # withdrawn once
            c.bills.withdraw_stored_material(lot["id"], actor="pm", reason="again")
        with self.assertRaises(BillError):  # a withdrawn lot is final
            c.bills.confirm_lot_evidence(lot["id"], gone["evidence_current_hash"], "pm")
        with self.assertRaises(BillError) as cm:
            w.certify({1: "55000"}, transfers=[{"lot_id": lot["id"], "amount": "1"}])
        self.assertIn("withdrawn", str(cm.exception))
        with self.assertRaises(sqlite3.DatabaseError):  # final at the storage level too
            c.db.execute("UPDATE stored_material_lots SET remaining_amount='10000.00' WHERE id=?", (lot["id"],))
        b2 = w.certify({1: "55000"})
        self.assertEqual((b2["cumulative_installed"], b2["cumulative_stored"], b2["amount_due"], b2["excluded_lots"]), ("55000.00", "0.00", "4500.00", []))
        w.post(b2["id"])
        self.assertEqual([e["action"] for e in c.audit.entries(entity_type="stored_material_lot", entity_id=lot["id"])],
                         ["stored_material.added", "stored_material.withdrawn"])

        # billed stored material is never withdrawn
        lot2, _, _ = w.lot("pump skid", "5000", line_no=2)
        b3 = w.certify({1: "55000"})
        self.assertEqual((b3["cumulative_stored"], b3["stored_added_this_period"], b3["amount_due"]), ("5000.00", "5000.00", "4500.00"))
        w.post(b3["id"])
        with self.assertRaises(BillError):
            c.bills.withdraw_stored_material(lot2["id"], actor="pm", reason="changed our mind")
        self.assertEqual((str(c.ledger.balance("1300")), str(c.ledger.balance("5000"))), ("5000.00", "55000.00"))
        w.assert_books(self)

    def test_a_lot_wholly_transferred_by_a_draft_can_still_be_confirmed(self):
        w = World()
        c = w.c
        lot, doc, _ = w.lot("valves", "10000")
        w.post(w.certify({1: "20000"})["id"])
        draft = w.certify({1: "30000"}, transfers=[{"lot_id": lot["id"], "amount": "10000"}])
        self.assertEqual(c.bills.lot(lot["id"])["remaining_amount"], "0.00")
        rev2 = w.revise(doc, "valves: delivery ticket reissued")
        with self.assertRaises(BillError):  # the draft transfers from a lot whose evidence was revised
            w.post(draft["id"])
        self.assertEqual(c.bills.get(draft["id"])["status"], "draft")
        confirmed = c.bills.confirm_lot_evidence(lot["id"], rev2["content_hash"], "pm")
        self.assertEqual((confirmed["evidence_status"], confirmed["remaining_amount"]), ("current", "0.00"))
        w.post(draft["id"])
        self.assertEqual([lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=draft["id"])],
                         [[("5000", "10000.00", "0.00"), ("1300", "0.00", "10000.00")]])
        self.assertEqual(str(c.ledger.balance("1300")), "0.00")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 10. hardening: storage guards against raw status and lot edits               #
# --------------------------------------------------------------------------- #

BILL_COLUMNS = ("id", "commitment_id", "period_id", "sequence", "status", "cumulative_installed", "cumulative_stored", "cumulative_gross", "cumulative_retainage",
                "cumulative_net", "prior_net", "amount_due", "retainage_this_period", "installed_this_period", "stored_added_this_period",
                "stored_transferred_this_period", "commitment_version", "content_hash", "created_at")


def raw_bill(c, commitment_id, sequence, status, figures, *, created_at=None, period_id="P1"):
    """A supplier bill written with raw SQL (installed, stored, gross, retainage, net, prior net, due, retainage this period,
    installed this period, stored added, stored transferred), as an older release or a probe would."""
    bid = new_id("bill")
    version = c.db.scalar("SELECT version FROM commitments WHERE id=?", (commitment_id,))
    vals = (bid, commitment_id, period_id, sequence, status, *figures, version, sha256_hex(bid), created_at or utcnow_iso())
    c.db.execute(f"INSERT INTO bills ({', '.join(BILL_COLUMNS)}) VALUES ({', '.join('?' * len(BILL_COLUMNS))})", vals)
    return bid


class StorageGuardTests(unittest.TestCase):
    def test_posted_bill_status_cannot_be_rewound_or_voided_with_raw_sql(self):
        w = World()
        c = w.c
        b = w.certify({1: "20000"})
        w.post(b["id"])  # 18,000 payable, 2,000 retained
        posted = c.bills.get(b["id"])
        probes = [
            ("UPDATE bills SET status='draft' WHERE id=?", (b["id"],)),
            ("UPDATE bills SET status='void' WHERE id=?", (b["id"],)),
            ("UPDATE bills SET retainage_this_period='0.00', amount_due='30000.00' WHERE id=?", (b["id"],)),
            ("DELETE FROM bills WHERE id=?", (b["id"],)),
            ("INSERT INTO bill_lines (id, bill_id, sov_line_id, cumulative_installed, prior_installed, installed_this_period, stored_added, stored_transferred) VALUES (?,?,?,?,?,?,?,?)",
             (new_id("bln"), b["id"], w.line(2), "40000.00", "0.00", "40000.00", "0.00", "0.00")),
        ]
        for sql, params in probes:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, params)
        with self.assertRaises(sqlite3.DatabaseError):  # a bill is born a draft
            raw_bill(c, w.cid, 9, "posted", ("40000.00", "0.00", "40000.00", "4000.00", "36000.00", "0.00", "36000.00", "4000.00", "40000.00", "0.00", "0.00"))
        draft = w.certify({1: "30000"})
        for sql, params in (("UPDATE bills SET status='posted' WHERE id=?", (draft["id"],)),
                            ("UPDATE bills SET status='paid' WHERE id=?", (draft["id"],)),
                            ("UPDATE bills SET status='posted', approval_id=?, journal_id=? WHERE id=?", (posted["approval_id"], posted["journal_id"], draft["id"]))):
            with self.subTest(sql=sql, params=params), self.assertRaises(sqlite3.DatabaseError):  # posted only with its own approved journal
                c.db.execute(sql, params)
        c.bills.void(draft["id"], actor="pm", reason="re-measure")
        with self.assertRaises(sqlite3.DatabaseError):  # void is final
            c.db.execute("UPDATE bills SET status='draft' WHERE id=?", (draft["id"],))
        self.assertEqual((c.bills.get(b["id"])["status"], c.bills.get(b["id"])["amount_due"]), ("posted", "18000.00"))
        ap = c.bills.ap_open_items(w.pid)
        self.assertEqual((ap["subledger_total"], ap["control_balance"]), ("18000.00", "18000.00"))
        ret = c.bills.retainage_open_items(w.pid)
        self.assertEqual((ret["subledger_total"], ret["control_balance"]), ("2000.00", "2000.00"))
        w.assert_books(self)

    def test_lot_storage_guards(self):
        w = World()
        c = w.c
        lot, doc, _ = w.lot("sheet piling", "1000")
        for sql in ("UPDATE stored_material_lots SET remaining_amount='9000.00' WHERE id=?",   # above the eligible amount
                    "UPDATE stored_material_lots SET remaining_amount='-1.00' WHERE id=?",
                    "UPDATE stored_material_lots SET remaining_amount='500' WHERE id=?",       # not canonical money
                    "UPDATE stored_material_lots SET location='   ' WHERE id=?",
                    "UPDATE stored_material_lots SET location='Somewhere else (synthetic)' WHERE id=?",
                    "UPDATE stored_material_lots SET withdrawn_at='2026-10-12T00:00:00Z', withdrawn_by='pm', withdrawal_reason='x' WHERE id=?",  # remaining left
                    "DELETE FROM stored_material_lots WHERE id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (lot["id"],))
        with self.assertRaises(sqlite3.DatabaseError):  # a new lot is never already withdrawn
            raw_lot(c, w.cid, w.line(2), "500.00", evidence_hash="probe-withdrawn", withdrawn_at="2026-10-12T00:00:00Z")
        rev2 = w.revise(doc, "sheet piling: insurance renewed")
        self.assertTrue(c.bills.lot(lot["id"])["frozen"])
        with self.assertRaises(sqlite3.DatabaseError):  # unfreezing without the audited confirmation
            c.db.execute("UPDATE stored_material_lots SET evidence_revision_id=?, evidence_hash=? WHERE id=?", (rev2["id"], rev2["content_hash"], lot["id"]))
        self.assertTrue(c.bills.lot(lot["id"])["frozen"])
        b1 = w.certify({1: "20000"})  # the frozen lot is left out
        w.post(b1["id"])
        with self.assertRaises(sqlite3.DatabaseError):  # a posted bill never acquires a lot it did not bill
            c.db.execute("UPDATE stored_material_lots SET billed_bill_id=? WHERE id=?", (b1["id"], lot["id"]))
        with self.assertRaises(sqlite3.DatabaseError):  # nor is a lot born billed by it
            raw_lot(c, w.cid, w.line(2), "500.00", evidence_hash="probe-billed", billed_bill_id=b1["id"])
        c.bills.confirm_lot_evidence(lot["id"], rev2["content_hash"], "pm")  # the audited path works
        b2 = w.certify({1: "20000"})
        self.assertEqual((b2["cumulative_stored"], b2["stored_added_this_period"]), ("1000.00", "1000.00"))
        w.post(b2["id"])
        with self.assertRaises(sqlite3.DatabaseError):  # and that billing history is permanent
            c.db.execute("UPDATE stored_material_lots SET billed_bill_id=NULL WHERE id=?", (lot["id"],))
        self.assertEqual(c.bills.lot(lot["id"])["billed_bill_id"], b2["id"])
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 11. hardening: closing a commitment                                          #
# --------------------------------------------------------------------------- #

class CommitmentCloseTests(unittest.TestCase):
    def test_close_refuses_open_work_and_a_raw_status_edit_never_closes(self):
        w = World()
        c = w.c
        lot, _, _ = w.lot("sheet piling", "10000")
        w.post(w.certify({1: "20000"})["id"])  # 3,000 retained
        draft = w.certify({1: "30000"}, transfers=[{"lot_id": lot["id"], "amount": "10000"}])
        ch = c.commitments.propose_change(w.cid, amount="1500", reason="extra sheet piling (synthetic)", sov_line_id=w.line(2), actor="pm")
        with self.assertRaises(CommitmentError) as cm:
            c.commitments.close(w.cid, actor="pm")
        self.assertIn("draft", str(cm.exception))
        c.bills.void(draft["id"], actor="pm", reason="re-measure")
        with self.assertRaises(CommitmentError) as cm:  # 10,000 stored material still carried in 1300
            c.commitments.close(w.cid, actor="pm")
        self.assertIn(lot["id"], str(cm.exception))
        w.post(w.certify({1: "30000"}, transfers=[{"lot_id": lot["id"], "amount": "10000"}])["id"])
        with self.assertRaises(CommitmentError) as cm:
            c.commitments.close(w.cid, actor="pm")
        self.assertIn("pending change", str(cm.exception))
        c.commitments.reject_change(ch["id"], actor="pm", reason="not instructed")
        with self.assertRaises(CommitmentError):
            c.commitments.close(w.cid, actor=" ")
        self.assertEqual((c.commitments.get(w.cid)["status"], c.commitments.closure(w.cid)), ("executed", None))

        closed = c.commitments.close(w.cid, actor="pm")
        closure = c.commitments.closure(w.cid)
        self.assertEqual((closed["status"], closure["basis"], closure["commitment_version"], closure["closed_by"], closure["closeout_approval_id"]),
                         ("closed", "direct", closed["version"], "pm", None))
        with self.assertRaises(CommitmentError):  # closed once
            c.commitments.close(w.cid, actor="pm")
        for sql in ("UPDATE commitments SET status='executed' WHERE id=?", "UPDATE commitments SET executed_amount='200000.00' WHERE id=?",
                    "UPDATE commitment_closures SET basis='legacy' WHERE commitment_id=?", "DELETE FROM commitment_closures WHERE commitment_id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (w.cid,))

        # a raw status edit does not close another commitment, so it never releases that retainage
        second = w.commitment("20000")
        w.post(w.certify({1: "20000"}, cid=second)["id"])  # 2,000 retained
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("UPDATE commitments SET status='closed' WHERE id=?", (second,))
        with self.assertRaises(BillError):
            c.approve_and_execute("retainage.release", second, actor_role="accountant", period_id="P1")
        ap = c.request_approval("retainage.release", w.cid, actor_role="accountant")
        self.assertEqual({k: ap["manifest"]["bindings"][k] for k in ("commitment_status", "commitment_version", "closed_at", "closure_basis", "closeout_approval_id")},
                         {"commitment_status": "closed", "commitment_version": closed["version"], "closed_at": closure["closed_at"],
                          "closure_basis": "direct", "closeout_approval_id": None})
        c.approve(ap["id"], approver="controller", approver_role="controller")
        res = c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(res.result["amount"], "3000.00")
        self.assertEqual(str(c.ledger.balance("2050")), "2000.00")
        self.assertEqual([e["action"] for e in c.audit.entries(entity_type="commitment", entity_id=w.cid) if e["action"].startswith("commitment.")],
                         ["commitment.created", "commitment.executed", "commitment.closed"])
        w.assert_books(self)

    def test_an_open_field_closeout_blocks_a_direct_close_and_its_acceptance_closes(self):
        w = World()
        c = w.c
        f = c.plugin("field")
        w.post(w.certify({1: "60000", 2: "40000"})["id"])  # 10,000 retained
        items = ["as_builts", "warranties", "final_lien_release"]
        f.set_closeout_requirements(w.cid, items, "pm")
        with self.assertRaises(CommitmentError) as cm:  # no direct close around an open closeout
            c.commitments.close(w.cid, actor="pm")
        self.assertIn("field.accept_closeout", str(cm.exception))
        for item in items:
            f.submit_closeout_item(w.cid, item, sha256_hex(f"synthetic closeout evidence: {item}".encode()), "pm")
        with self.assertRaises(CommitmentError):  # ready is not accepted
            c.commitments.close(w.cid, actor="pm")
        res = c.approve_and_execute("field.accept_closeout", w.cid, actor_role="pm", period_id="P1")
        self.assertEqual(res.result["commitment_status"], "closed")
        accepted_by = f.closeout(w.cid)["approval_id"]
        closure = c.commitments.closure(w.cid)
        self.assertEqual((closure["basis"], closure["closeout_approval_id"]), ("closeout_accepted", accepted_by))
        ap = c.request_approval("retainage.release", w.cid, actor_role="accountant")
        self.assertEqual((ap["manifest"]["bindings"]["closure_basis"], ap["manifest"]["bindings"]["closeout_approval_id"]), ("closeout_accepted", accepted_by))
        c.approve(ap["id"], approver="controller", approver_role="controller")
        self.assertEqual(c.execute(ap["id"], actor="accountant", period_id="P1").result["amount"], "10000.00")
        self.assertEqual(str(c.ledger.balance("2050")), "0.00")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 12. hardening: released retainage and its payments in the AP subledger       #
# --------------------------------------------------------------------------- #

class RetainagePaymentMatchingTests(unittest.TestCase):
    def test_retainage_payments_are_matched_per_supplier_and_project_like_payments(self):
        w = World()
        c = w.c
        second = w.commitment("20000")  # same supplier, same project
        w.post(w.certify({1: "30000"})["id"])              # 27,000 payable, 3,000 retained
        w.post(w.certify({1: "20000"}, cid=second)["id"])  # 18,000 payable, 2,000 retained
        c.commitments.close(w.cid, actor="pm")
        c.approve_and_execute("retainage.release", w.cid, actor_role="accountant", period_id="P1")  # 3,000 now payable
        # payments scopes released retainage to the supplier and project, whichever commitment is named
        rm = c.request_approval("payment.release_retainage", second, actor_role="treasury")
        self.assertEqual(rm["manifest"]["amounts"], {"amount": "3000.00"})
        c.approve(rm["id"], approver="treasury", approver_role="treasury")
        c.execute(rm["id"], actor="treasury")
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        ap = c.bills.ap_open_items(w.pid)
        self.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("45000.00", "45000.00", True))
        released = [(i["commitment_id"], i["amount_due"], i["paid"], i["open"]) for i in ap["items"] if i.get("kind") == "retainage_release"]
        self.assertEqual(released, [(w.cid, "3000.00", "3000.00", "0.00")])
        with self.assertRaises(PaymentError):  # paid once
            c.request_approval("payment.release_retainage", w.cid, actor_role="treasury")

        c.commitments.close(second, actor="pm")
        c.approve_and_execute("retainage.release", second, actor_role="accountant", period_id="P1")
        c.approve_and_execute("payment.release_retainage", second, actor_role="treasury", actor="treasury")
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        ap = c.bills.ap_open_items()
        self.assertEqual((ap["subledger_total"], ap["control_balance"], ap["reconciled"]), ("45000.00", "45000.00", True))
        released = [(i["commitment_id"], i["amount_due"], i["paid"], i["open"]) for i in ap["items"] if i.get("kind") == "retainage_release"]
        self.assertEqual(released, [(w.cid, "3000.00", "3000.00", "0.00"), (second, "2000.00", "2000.00", "0.00")])
        self.assertEqual(str(c.ledger.balance("2050")), "0.00")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 13. hardening: billing history of lots recorded by an older release          #
# --------------------------------------------------------------------------- #

class LegacyBillingHistoryTests(unittest.TestCase):
    def test_billing_history_follows_the_audit_order_when_timestamps_tie(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "legacy-bills.sqlite")
        tick = "2026-10-12T03:00:00Z"  # every record below lands in the same second
        legacy_catalog = [e for e in core_db.SCHEMA_CATALOG
                          if e[1] not in (BILLS_SCHEMA_NAME, BILLS_HARDENING_SCHEMA_NAME, BILLS_LIFECYCLE_SCHEMA_NAME, *AFTER_LIFECYCLE)]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy_catalog):
            w = World(path)
            c = w.c
            self.assertNotIn("billed_bill_id", {r["name"] for r in c.db.query("PRAGMA table_info(stored_material_lots)")})

            def legacy_lot(label, amount):
                lid = new_id("lot")
                h = sha256_hex(f"older-release free-text evidence: {label}".encode())
                c.db.execute("INSERT INTO stored_material_lots (id, commitment_id, sov_line_id, description, eligible_amount, remaining_amount, evidence_hash, location, created_at) "
                             "VALUES (?,?,?,?,?,?,?,?,?)", (lid, w.cid, w.line(1), label, amount, amount, h, "Laydown yard A (synthetic)", tick))
                c.audit.record("pm", "stored_material.added", "stored_material_lot", lid, {"commitment_id": w.cid, "sov_line_id": w.line(1), "eligible_amount": amount, "evidence_hash": h})
                return lid

            def legacy_bill(sequence, status, figures):
                bid = raw_bill(c, w.cid, sequence, status, figures, created_at=tick)
                c.audit.record("pm", "bill.certified", "bill", bid, {"commitment_id": w.cid, "sequence": sequence, "amount_due": figures[6]})
                return bid

            lot1 = legacy_lot("PZ sheet piling", "10000.00")
            bill1 = legacy_bill(1, "posted", ("20000.00", "10000.00", "30000.00", "3000.00", "27000.00", "0.00", "27000.00", "3000.00", "20000.00", "10000.00", "0.00"))
            j = c.ledger.post(period_id="P1", description="Supplier bill 1 (older release)", source_type="bill", source_id=bill1, source_version="2", posted_by="accountant",
                              lines=[{"account": "5000", "debit": "20000", "project_id": w.pid}, {"account": "1300", "debit": "10000", "project_id": w.pid},
                                     {"account": "2000", "credit": "27000", "project_id": w.pid}, {"account": "2050", "credit": "3000", "project_id": w.pid}])
            c.db.execute("UPDATE bills SET journal_id=? WHERE id=?", (j["id"], bill1))
            lot2 = legacy_lot("Dewatering pumps", "15000.00")  # recorded after bill 1, in the same second
            bill2 = legacy_bill(2, "draft", ("20000.00", "25000.00", "45000.00", "4500.00", "40500.00", "27000.00", "13500.00", "1500.00", "0.00", "15000.00", "0.00"))
            c.db.close()

        reopened = Cipher(path)
        try:
            c = reopened
            status = {v["name"]: v for v in c.db.schema_status()["versions"]}
            self.assertTrue(status[BILLS_SCHEMA_NAME]["applied"] and status[BILLS_HARDENING_SCHEMA_NAME]["applied"] and status[BILLS_LIFECYCLE_SCHEMA_NAME]["applied"])
            # the timestamp rule alone attributes the tied lot to bill 1
            tied = c.db.scalar("SELECT id FROM bills WHERE commitment_id=? AND status != 'void' AND created_at >= ? ORDER BY sequence LIMIT 1", (w.cid, tick))
            self.assertEqual(tied, bill1)
            # the repaired history follows the audit order: lot 2 was first billed by draft bill 2
            self.assertEqual((c.bills.lot(lot1)["billed_bill_id"], c.bills.lot(lot2)["billed_bill_id"]), (bill1, bill2))
            self.assertEqual([lot["evidence_status"] for lot in c.bills.lots(w.cid)], ["unbound", "unbound"])
            # so the draft that first bills the never-verified lot cannot be posted
            with self.assertRaises(BillError) as cm:
                c.approve_and_execute("bill.approve", bill2, actor_role="accountant", actor="accountant")
            self.assertIn(lot2, str(cm.exception))
            self.assertEqual((c.bills.get(bill2)["status"], str(c.ledger.balance("1300"))), ("draft", "10000.00"))
            self.assertEqual(c.bills.stored_material_items()["items"][0]["lots_requiring_confirmation"], [lot1])
            self.assertEqual(c.db.migrate(), [])
            self.assertTrue(c.ledger.trial_balance()["balanced"])
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            reopened.db.close()


# --------------------------------------------------------------------------- #
# 14. supplier credit notes (bill.credit_note)                                 #
# --------------------------------------------------------------------------- #

def credit_evidence(w, label, *, kind="supplier_credit_note"):
    doc = w.c.evidence.register_document(project_id=w.pid, kind=kind, title=f"Supplier credit note: {label}", actor="accountant")
    rev = w.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic supplier credit note: {label}".encode(), actor="accountant")
    return doc, rev


def granted(c, operation, subject_id, *, actor_role="accountant", approver_role="controller"):
    ap = c.request_approval(operation, subject_id, actor_role=actor_role, requested_by="accountant")
    c.approve(ap["id"], approver=approver_role, approver_role=approver_role)
    return ap


def release_open_payable(c, bill_id):
    """Release a payment of a bill for exactly its open payable and return the intent.  When the
    service's payment.release manifest already binds the open payable it is used as is; while
    payments still binds the amount due (refused by the storage guard for a credited bill), the
    probe binds the open payable itself -- what payments.manifest_for_bill must bind -- and runs
    the same approval and intent steps the service runs."""
    open_amt = fmt(c.bills.open_payable(bill_id))
    m = c.payments.manifest_for_bill(bill_id, actor_role="treasury")
    if m["amounts"]["amount"] == open_amt:
        intent_id = c.approve_and_execute("payment.release", bill_id, actor_role="treasury", actor="treasury").result["intent"]
        return c.payments.get(intent_id)
    m["amounts"]["amount"] = open_amt
    ap = c.approvals.request(m, requested_by="treasury")
    c.approve(ap["id"], approver="treasury", approver_role="treasury")
    c.approvals.consume(ap["id"], current_manifest=m, consumer="treasury")
    return c.payments.create_intent(manifest=m, approval_id=ap["id"], bill_id=bill_id, note="bill payment", actor="treasury")


class SupplierCreditNoteTests(unittest.TestCase):
    def test_credit_note_posts_dr_ap_cr_cost_and_the_subledger_follows(self):
        w = World()
        c = w.c
        b = w.certify({1: "30000"})
        w.post(b["id"])  # 27,000 payable, 3,000 retained
        doc, rev = credit_evidence(w, "CN-0001 back-charge for damaged sheet piling")
        n = c.bills.prepare_credit_note(b["id"], "1500.00", "back-charge: damaged sheet piling replaced by others", rev["content_hash"], "accountant")
        self.assertEqual((n["status"], n["amount"], n["evidence_document_id"], n["evidence_revision_id"], n["evidence_current"]),
                         ("draft", "1500.00", doc["id"], rev["id"], True))
        ap = granted(c, "bill.credit_note", n["id"])
        m = ap["manifest"]
        self.assertEqual((m["subject"], m["amounts"], m["entity"]), ({"type": "supplier_credit_note", "id": n["id"]},
                                                                     {"credit": "1500.00", "open_payable": "27000.00"}, ENTITY))
        self.assertEqual((m["bindings"]["bill_hash"], m["bindings"]["open_payable"], m["bindings"]["evidence_hash"], m["bindings"]["source_type"]),
                         (b["content_hash"], "27000.00", rev["content_hash"], "supplier_credit_note"))
        self.assertEqual([(ln["account"], ln["debit"], ln["credit"]) for ln in m["bindings"]["journal_preview"]],
                         [("2000", "1500.00", "0.00"), ("5000", "0.00", "1500.00")])
        res = c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual((res.result["status"], res.result["amount"], res.result["open_payable"]), ("posted", "1500.00", "25500.00"))
        self.assertTrue(c.execute(ap["id"], actor="accountant", period_id="P1").replayed)
        j = c.ledger.journal(res.result["journal_id"])
        self.assertEqual(lines_of(j), [("2000", "1500.00", "0.00"), ("5000", "0.00", "1500.00")])
        self.assertEqual((j["source_type"], j["source_id"], j["approval_id"], j["period_id"]), ("supplier_credit_note", n["id"], ap["id"], "P1"))
        self.assertEqual({(ln["project_id"], ln["party_id"]) for ln in j["lines"]}, {(w.pid, w.supplier["id"])})
        self.assertEqual((str(c.bills.open_payable(b["id"])), str(c.bills.credited(b["id"]))), ("25500.00", "1500.00"))
        ap_items = c.bills.ap_open_items(w.pid)
        item = next(i for i in ap_items["items"] if i["bill_id"] == b["id"])
        self.assertEqual((item["amount_due"], item["paid"], item["credited"], item["open"]), ("27000.00", "0.00", "1500.00", "25500.00"))
        self.assertEqual((ap_items["subledger_total"], ap_items["control_balance"]), ("25500.00", "25500.00"))
        self.assertEqual((str(c.ledger.balance("2000")), str(c.ledger.balance("5000")), str(c.ledger.balance("2050"))), ("25500.00", "28500.00", "3000.00"))
        self.assertEqual(c.bills.credit_note(n["id"])["status"], "posted")
        # the credit-note journal is corrected through its own module, never a bare journal.reverse
        with self.assertRaises(LedgerError):
            c.ledger.prepare_reversal(j["id"], "reverse the credit", "controller")
        for sql in ("UPDATE bill_credit_notes SET amount='15.00' WHERE id=?", "UPDATE bill_credit_notes SET status='cancelled' WHERE id=?",
                    "DELETE FROM bill_credit_notes WHERE id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (n["id"],))
        w.assert_books(self)

    def test_credit_cannot_exceed_the_open_payable(self):
        w = World()
        c = w.c
        draft = w.certify({1: "30000"})
        _, rev = credit_evidence(w, "CN-1")
        with self.assertRaises(BillError):  # a draft bill has no payable to credit
            c.bills.prepare_credit_note(draft["id"], "100.00", "early credit", rev["content_hash"], "accountant")
        w.post(draft["id"])
        b = draft
        _, wrong_kind = credit_evidence(w, "a stored-material record", kind="stored_material_evidence")
        doc_old, rev_old = credit_evidence(w, "CN-old")
        w.c.evidence.add_revision(document_id=doc_old["id"], content=b"synthetic supplier credit note reissued", actor="accountant")
        for label, amount, evidence in (("above the open payable", "27000.01", rev["content_hash"]), ("zero", "0", rev["content_hash"]),
                                        ("negative", "-1.00", rev["content_hash"]), ("float", 100.0, rev["content_hash"]),
                                        ("sub-cent", "10.005", rev["content_hash"]), ("wrong document kind", "100.00", wrong_kind["content_hash"]),
                                        ("superseded revision", "100.00", rev_old["content_hash"]), ("unknown hash", "100.00", sha256_hex(b"never stored")),
                                        ("no evidence", "100.00", "")):
            with self.subTest(case=label), self.assertRaises(BillError):
                c.bills.prepare_credit_note(b["id"], amount, "credit", evidence, "accountant")
        with self.assertRaises(BillError):
            c.bills.prepare_credit_note(b["id"], "100.00", "  ", rev["content_hash"], "accountant")
        n1 = c.bills.prepare_credit_note(b["id"], "20000.00", "scope removed (synthetic)", rev["content_hash"], "accountant")
        with self.assertRaises(BillError):  # one credit-note document backs one credit note
            c.bills.prepare_credit_note(b["id"], "1.00", "again", rev["content_hash"], "accountant")
        _, rev2 = credit_evidence(w, "CN-2")
        with self.assertRaises(BillError):  # the draft reserves its 20,000: 7,000 is left
            c.bills.prepare_credit_note(b["id"], "7000.01", "second credit", rev2["content_hash"], "accountant")
        n2 = c.bills.prepare_credit_note(b["id"], "7000.00", "second credit", rev2["content_hash"], "accountant")
        ap2 = granted(c, "bill.credit_note", n2["id"])  # binds the open payable of 27,000
        ap1 = granted(c, "bill.credit_note", n1["id"])
        c.execute(ap1["id"], actor="accountant", period_id="P1")
        with self.assertRaises(StaleApprovalError):  # the open payable moved to 7,000 after ap2 was granted
            c.execute(ap2["id"], actor="accountant", period_id="P1")
        self.assertEqual(c.approvals.get(ap2["id"])["status"], "invalidated")
        ap2b = granted(c, "bill.credit_note", n2["id"])
        self.assertEqual(ap2b["manifest"]["amounts"], {"credit": "7000.00", "open_payable": "7000.00"})
        c.execute(ap2b["id"], actor="accountant", period_id="P1")
        self.assertEqual(str(c.bills.open_payable(b["id"])), "0.00")
        _, rev3 = credit_evidence(w, "CN-3")
        with self.assertRaises(BillError):  # nothing is open any more
            c.bills.prepare_credit_note(b["id"], "0.01", "third credit", rev3["content_hash"], "accountant")
        with self.assertRaises(BillIneligible):  # a posted credit note is not posted twice
            c.request_approval("bill.credit_note", n1["id"], actor_role="accountant")
        self.assertEqual((str(c.ledger.balance("2000")), str(c.ledger.balance("5000"))), ("0.00", "3000.00"))
        w.assert_books(self)

    def test_cancel_period_and_payment_interplay(self):
        w = World()
        c = w.c
        b = w.certify({1: "30000"})
        w.post(b["id"])
        pay = granted(c, "payment.release", b["id"], actor_role="treasury", approver_role="treasury")  # granted for the full 27,000
        _, rev = credit_evidence(w, "CN-10")
        n = c.bills.prepare_credit_note(b["id"], "2000.00", "liquidated damages (synthetic)", rev["content_hash"], "accountant")
        ap = granted(c, "bill.credit_note", n["id"])
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")  # the approval survives: execute into an open period
        res = c.execute(ap["id"], actor="accountant")  # defaults to the latest open period
        self.assertEqual(res.result["period_id"], "P2")
        self.assertEqual(c.approvals.get(pay["id"])["status"], "invalidated")  # the payment approval was for 27,000
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            c.execute(pay["id"], actor="treasury")
        # a draft is cancelled once and its approval goes stale
        _, rev2 = credit_evidence(w, "CN-11")
        n2 = c.bills.prepare_credit_note(b["id"], "500.00", "rebate (synthetic)", rev2["content_hash"], "accountant")
        ap_n2 = granted(c, "bill.credit_note", n2["id"])
        cancelled = c.bills.cancel_credit_note(n2["id"], "supplier withdrew the rebate", "accountant")
        self.assertEqual((cancelled["status"], cancelled["cancelled_by"]), ("cancelled", "accountant"))
        self.assertEqual(c.approvals.get(ap_n2["id"])["status"], "invalidated")
        with self.assertRaises(BillError):
            c.bills.cancel_credit_note(n2["id"], "again", "accountant")
        # the cancelled document may back a new credit note
        n3 = c.bills.prepare_credit_note(b["id"], "400.00", "rebate reissued (synthetic)", rev2["content_hash"], "accountant")
        self.assertEqual(n3["status"], "draft")
        # a payment in flight stops a new credit; the payment is for the 25,000 still open, not the 27,000 due
        intent = release_open_payable(c, b["id"])
        self.assertEqual((intent["amount"], intent["status"]), ("25000.00", "queued"))
        _, rev4 = credit_evidence(w, "CN-12")
        with self.assertRaises(BillError):
            c.bills.prepare_credit_note(b["id"], "100.00", "in flight", rev4["content_hash"], "accountant")
        with self.assertRaises(BillIneligible):
            c.request_approval("bill.credit_note", n3["id"], actor_role="accountant")
        self.assertEqual(str(c.bills.open_payable(b["id"])), "25000.00")
        # once paid, the bill has nothing open: AP nets to zero, never below
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        self.assertEqual((c.bills.get(b["id"])["status"], str(c.bills.open_payable(b["id"])), str(c.ledger.balance("2000"))), ("paid", "0.00", "0.00"))
        with self.assertRaises(BillIneligible):  # the draft credit note has nothing left to credit
            c.request_approval("bill.credit_note", n3["id"], actor_role="accountant")
        w.assert_books(self)


class CreditedBillPaymentTests(unittest.TestCase):
    """A payment released after a supplier credit note pays the open payable, never the amount due."""

    def credited(self, amount):
        w = World()
        c = w.c
        b = w.certify({1: "30000"})
        w.post(b["id"])  # 27,000 due
        early = granted(c, "payment.release", b["id"], actor_role="treasury", approver_role="treasury")  # bound to 27,000
        _, rev = credit_evidence(w, f"CN-{amount}")
        n = c.bills.prepare_credit_note(b["id"], amount, "back-charge for damaged sheet piles (synthetic)", rev["content_hash"], "accountant")
        c.approve_and_execute("bill.credit_note", n["id"], actor_role="accountant", actor="accountant", period_id="P1")
        return w, c, b, early

    def assert_release_never_overpays(self, c, bill_id):
        """However payments builds the release, a credited bill's approval is never for more than its open payable."""
        open_amt = fmt(c.bills.open_payable(bill_id))
        try:
            ap = c.request_approval("payment.release", bill_id, actor_role="treasury", requested_by="treasury")
        except sqlite3.IntegrityError as exc:  # payments binds the amount due: refused before anyone can approve it
            self.assertIn("open payable", str(exc))
            return None
        self.assertEqual(ap["manifest"]["amounts"]["amount"], open_amt)
        c.reject(ap["id"], approver="treasury", reason="probe only")
        return ap

    def test_payment_after_a_credit_pays_the_open_payable_and_ap_never_goes_negative(self):
        w, c, b, early = self.credited("2000.00")
        self.assertEqual(c.approvals.get(early["id"])["status"], "invalidated")  # the credit made the 27,000 approval stale
        self.assertEqual(str(c.bills.open_payable(b["id"])), "25000.00")
        self.assert_release_never_overpays(c, b["id"])
        # a release built for the full amount due never becomes a payment intent, by any path
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            c.payments.create_intent(manifest=early["manifest"], approval_id=early["id"], bill_id=b["id"], note="bill payment", actor="treasury")
        self.assertIn("overpay", str(cm.exception))
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM payment_intents WHERE bill_id=?", (b["id"],)), 0)
        # paying the open payable settles the bill exactly
        intent = release_open_payable(c, b["id"])
        self.assertEqual(intent["amount"], "25000.00")
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        c.reconcile_payments()
        self.assertEqual(c.bills.get(b["id"])["status"], "paid")
        item = next(i for i in c.bills.ap_open_items(w.pid)["items"] if i["bill_id"] == b["id"])
        self.assertEqual((item["amount_due"], item["paid"], item["credited"], item["open"]), ("27000.00", "25000.00", "2000.00", "0.00"))
        self.assertEqual((str(c.bills.open_payable(b["id"])), str(c.ledger.balance("2000")), str(c.ledger.balance("5000"))), ("0.00", "0.00", "28000.00"))
        with self.assertRaises(PaymentError):  # paid: nothing more is released
            c.request_approval("payment.release", b["id"], actor_role="treasury")
        w.assert_books(self)

    def test_a_fully_credited_bill_releases_nothing(self):
        w, c, b, _ = self.credited("27000.00")
        self.assertEqual((str(c.bills.open_payable(b["id"])), str(c.ledger.balance("2000"))), ("0.00", "0.00"))
        ap = None
        try:
            ap = self.assert_release_never_overpays(c, b["id"])
        except PaymentError:  # a payments release that binds the open payable refuses a zero payment
            pass
        self.assertIsNone(ap)
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM payment_intents WHERE bill_id=?", (b["id"],)), 0)
        item = next(i for i in c.bills.ap_open_items(w.pid)["items"] if i["bill_id"] == b["id"])
        self.assertEqual((item["credited"], item["open"]), ("27000.00", "0.00"))
        w.assert_books(self)

    def test_an_uncredited_bill_still_releases_its_amount_due(self):
        w = World()
        c = w.c
        b = w.certify({1: "30000"})
        w.post(b["id"])
        out = c.approve_and_execute("payment.release", b["id"], actor_role="treasury", actor="treasury")
        self.assertEqual(out.result["amount"], "27000.00")
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        self.assertEqual((c.bills.get(b["id"])["status"], str(c.ledger.balance("2000"))), ("paid", "0.00"))
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 15. posted-bill correction (bill.correct)                                    #
# --------------------------------------------------------------------------- #

class BillCorrectionTests(unittest.TestCase):
    def two_bills(self):
        w = World()
        lot1, _, _ = w.lot("sheet piling", "10000")
        b1 = w.certify({1: "20000"})
        w.post(b1["id"])  # 30,000 gross, 3,000 retained, 27,000 due
        lot2, _, _ = w.lot("dewatering pumps", "5000")
        b2 = w.certify({1: "45000"}, transfers=[{"lot_id": lot1["id"], "amount": "10000"}])
        w.post(b2["id"])  # 50,000 gross, 5,000 retained, 18,000 due
        return w, lot1, lot2, b1, b2

    def test_correction_reverses_the_bill_and_a_replacement_certifies_exactly(self):
        w, lot1, lot2, b1, b2 = self.two_bills()
        c = w.c
        originals = [lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=b2["id"])]
        self.assertEqual(originals, [[("5000", "10000.00", "0.00"), ("1300", "0.00", "10000.00")],
                                     [("5000", "15000.00", "0.00"), ("1300", "5000.00", "0.00"), ("2000", "0.00", "18000.00"), ("2050", "0.00", "2000.00")]])
        reason = "the sheet piling transfer was certified a period early (synthetic)"
        req = c.bills.prepare_correction(b2["id"], reason, "accountant")
        self.assertEqual((req["status"], req["reason"], req["bill_id"]), ("pending", reason, b2["id"]))
        ap = granted(c, "bill.correct", b2["id"])
        bound = ap["manifest"]["bindings"]
        self.assertEqual((bound["request"]["id"], bound["reason"], bound["bill_hash"], bound["restore_transfers"], bound["unbill_lots"], len(bound["journals"])),
                         (req["id"], reason, b2["content_hash"], [{"lot_id": lot1["id"], "amount": "10000.00"}], [lot2["id"]], 2))
        self.assertEqual(ap["manifest"]["amounts"], {"amount_due": "18000.00", "retainage_this_period": "2000.00", "cumulative_gross": "50000.00"})
        res = c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual((res.result["status"], res.result["period_id"], res.result["unbilled_lots"]), ("corrected", "P1", [lot2["id"]]))
        self.assertEqual(res.result["restored_lots"], [{"lot_id": lot1["id"], "amount": "10000.00", "remaining": "10000.00"}])
        reversals = [c.ledger.journal(jid) for jid in res.result["reversal_journals"]]
        self.assertEqual([lines_of(j) for j in reversals],
                         [[("5000", "0.00", "10000.00"), ("1300", "10000.00", "0.00")],
                          [("5000", "0.00", "15000.00"), ("1300", "0.00", "5000.00"), ("2000", "18000.00", "0.00"), ("2050", "2000.00", "0.00")]])
        for rev, orig in zip(reversals, c.ledger.journals(source_type="bill", source_id=b2["id"])):
            self.assertEqual((rev["reversal_of"], rev["approval_id"], rev["period_id"], rev["source_type"]), (orig["id"], ap["id"], "P1", "bill"))
            self.assertIn(reason, rev["description"])
        corrected = c.bills.get(b2["id"])
        self.assertEqual((corrected["status"], corrected["correction_id"], corrected["amount_due"]), ("corrected", req["id"], "18000.00"))
        done = c.bills.correction(req["id"])
        self.assertEqual((done["status"], done["approval_id"], done["period_id"], done["reversal_journals"]),
                         ("executed", ap["id"], "P1", res.result["reversal_journals"]))
        self.assertEqual((c.bills.lot(lot1["id"])["remaining_amount"], c.bills.lot(lot1["id"])["billed_bill_id"]), ("10000.00", b1["id"]))
        self.assertEqual((c.bills.lot(lot2["id"])["remaining_amount"], c.bills.lot(lot2["id"])["billed_bill_id"]), ("5000.00", None))
        self.assertEqual([str(c.ledger.balance(a)) for a in ("5000", "1300", "2000", "2050")], ["20000.00", "10000.00", "27000.00", "3000.00"])
        self.assertEqual((c.bills.retainage_open_items(w.pid)["subledger_total"], c.bills.stored_material_items(w.pid)["subledger_total"],
                          c.bills.ap_open_items(w.pid)["subledger_total"]), ("3000.00", "10000.00", "27000.00"))
        self.assertEqual(c.bills.latest(w.cid)["id"], b1["id"])
        w.assert_books(self)

        # the replacement certifies from bill 1's progress with the same figures and posts the same journals
        b3 = w.certify({1: "45000"}, transfers=[{"lot_id": lot1["id"], "amount": "10000"}])
        keys = ("cumulative_installed", "cumulative_stored", "cumulative_gross", "cumulative_retainage", "cumulative_net", "prior_net", "amount_due",
                "retainage_this_period", "installed_this_period", "stored_added_this_period", "stored_transferred_this_period")
        self.assertEqual({k: b3[k] for k in keys}, {k: b2[k] for k in keys})
        self.assertEqual((b3["sequence"], b3["status"]), (3, "draft"))
        w.post(b3["id"])
        self.assertEqual([lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=b3["id"])], originals)
        self.assertEqual([str(c.ledger.balance(a)) for a in ("5000", "1300", "2000", "2050")], ["45000.00", "5000.00", "45000.00", "5000.00"])
        self.assertEqual((c.bills.lot(lot1["id"])["remaining_amount"], c.bills.lot(lot2["id"])["billed_bill_id"]), ("0.00", b3["id"]))
        self.assertEqual([e["action"] for e in c.audit.entries(entity_type="bill", entity_id=b2["id"]) if e["action"].startswith("bill.correct")],
                         ["bill.correction_requested", "bill.corrected"])
        w.assert_books(self)

    def test_correction_refusals(self):
        w, lot1, lot2, b1, b2 = self.two_bills()
        c = w.c
        with self.assertRaises(BillError):  # only the commitment's latest bill
            c.bills.prepare_correction(b1["id"], "wrong bill", "accountant")
        with self.assertRaises(BillIneligible):  # the reason is recorded first
            c.request_approval("bill.correct", b2["id"], actor_role="accountant")
        self.assertEqual(c.ricky.propose("bill.correct", actor_role="accountant", context={"bill_id": b2["id"]})["decision"], "abstained")
        with self.assertRaises(BillError):
            c.bills.prepare_correction(b2["id"], "   ", "accountant")
        req = c.bills.prepare_correction(b2["id"], "re-measure (synthetic)", "accountant")
        self.assertEqual(c.ricky.propose("bill.correct", actor_role="accountant", context={"bill_id": b2["id"]})["decision"], "proposed")
        self.assertEqual(c.ricky.propose("bill.correct", actor_role="estimator", context={"bill_id": b2["id"]})["decision"], "abstained")
        with self.assertRaises(BillError):  # one pending request per bill
            c.bills.prepare_correction(b2["id"], "again", "accountant")
        with self.assertRaises(RoleNotAuthorised):
            c.request_approval("bill.correct", b2["id"], actor_role="pm")
        # a cancelled request makes its approval stale
        ap = granted(c, "bill.correct", b2["id"])
        c.bills.cancel_correction(req["id"], "measured again: the bill stands", "accountant")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        # a payment released after the approval makes it stale too
        c.bills.prepare_correction(b2["id"], "re-measure, second look (synthetic)", "accountant")
        ap2 = granted(c, "bill.correct", b2["id"])
        c.approve_and_execute("payment.release", b2["id"], actor_role="treasury", actor="treasury")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap2["id"], actor="accountant", period_id="P1")
        self.assertEqual((c.approvals.get(ap2["id"])["status"], c.bills.get(b2["id"])["status"]), ("invalidated", "posted"))
        self.assertEqual(str(c.ledger.balance("2000")), "45000.00")
        # raw SQL never marks a bill corrected
        pending = c.bills.corrections(b2["id"])[-1]
        for sql, params in (("UPDATE bills SET status='corrected' WHERE id=?", (b2["id"],)),
                            ("UPDATE bills SET status='corrected', correction_id=?, corrected_at='2026-10-12T00:00:00Z' WHERE id=?", (pending["id"], b2["id"])),
                            ("UPDATE stored_material_lots SET billed_bill_id=NULL WHERE id=?", (lot2["id"],)),
                            ("UPDATE bill_corrections SET status='executed' WHERE id=?", (pending["id"],)),
                            ("DELETE FROM bill_corrections WHERE id=?", (pending["id"],))):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, params)
        w.assert_books(self)

    def test_paid_or_credited_bills_are_not_corrected_and_a_corrected_bill_is_final(self):
        w, lot1, lot2, b1, b2 = self.two_bills()
        c = w.c
        _, rev = credit_evidence(w, "CN-20")
        n = c.bills.prepare_credit_note(b2["id"], "100.00", "rebate (synthetic)", rev["content_hash"], "accountant")
        with self.assertRaises(BillError):  # a credited bill (even a draft credit) is not corrected
            c.bills.prepare_correction(b2["id"], "re-measure", "accountant")
        c.bills.cancel_credit_note(n["id"], "superseded by the correction", "accountant")
        c.bills.prepare_correction(b2["id"], "re-measure (synthetic)", "accountant")
        c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        c.close_period("P1")
        ap = granted(c, "bill.correct", b2["id"])
        with self.assertRaises(PeriodNotOpen):  # a closed period never receives the reversal
            c.execute(ap["id"], actor="accountant", period_id="P1")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")
        res = c.execute(ap["id"], actor="accountant")  # the current open period
        self.assertEqual(res.result["period_id"], "P2")
        self.assertEqual({c.ledger.journal(j)["period_id"] for j in res.result["reversal_journals"]}, {"P2"})
        self.assertEqual(c.ledger.trial_balance("P1")["total_debit"], c.ledger.trial_balance("P1")["total_credit"])
        with self.assertRaises(PaymentError):  # a corrected bill is never paid
            c.request_approval("payment.release", b2["id"], actor_role="treasury")
        _, rev2 = credit_evidence(w, "CN-21")
        with self.assertRaises(BillError):  # nor credited
            c.bills.prepare_credit_note(b2["id"], "1.00", "late rebate", rev2["content_hash"], "accountant")
        with self.assertRaises(BillError):  # nor corrected twice
            c.bills.prepare_correction(b2["id"], "again", "accountant")
        for sql in ("UPDATE bills SET status='posted' WHERE id=?", "UPDATE bills SET amount_due='1.00' WHERE id=?",
                    "UPDATE bills SET correction_id=NULL, corrected_at=NULL WHERE id=?", "DELETE FROM bills WHERE id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (b2["id"],))
        # bill 1 is paid: once it is the latest bill again it still cannot be corrected
        c.approve_and_execute("payment.release", b1["id"], actor_role="treasury", actor="treasury")
        self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
        with self.assertRaises(BillError):
            c.bills.prepare_correction(b1["id"], "too late: paid", "accountant")
        w.assert_books(self)

    def test_older_workspace_is_rebuilt_with_every_bill_kept(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "pre-corrections.sqlite")
        older = [e for e in core_db.SCHEMA_CATALOG if e[1] not in (BILLS_LIFECYCLE_SCHEMA_NAME, *AFTER_LIFECYCLE)]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", older):
            w = World(path)
            c = w.c
            self.assertNotIn("corrected", c.db.scalar("SELECT sql FROM sqlite_master WHERE type='table' AND name='bills'"))
            lot1, _, _ = w.lot("sheet piling", "10000")
            b1 = w.certify({1: "20000"})
            w.post(b1["id"])
            c.approve_and_execute("payment.release", b1["id"], actor_role="treasury", actor="treasury")
            self.assertEqual([r["status"] for r in c.dispatch_payments()], ["accepted"])
            b2 = w.certify({1: "45000"}, transfers=[{"lot_id": lot1["id"], "amount": "10000"}])
            w.post(b2["id"])
            draft = w.certify({2: "1000"})
            before = c.db.query("SELECT * FROM bills ORDER BY sequence")
            bill_triggers = {r["name"] for r in c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='bills'")}
            counts = {t: c.db.scalar(f"SELECT COUNT(*) FROM {t}") for t in ("bills", "bill_lines", "bill_transfers", "payment_intents", "stored_material_lots")}
            c.db.close()
        upgraded = Cipher(path)
        try:
            c = upgraded
            status = {v["name"]: v for v in c.db.schema_status()["versions"]}
            self.assertTrue(status[BILLS_LIFECYCLE_SCHEMA_NAME]["applied"])
            self.assertTrue(all(status[name]["applied"] for name in AFTER_LIFECYCLE))  # applied after the rebuild, so their bills guards survive it
            self.assertEqual(c.db.schema_status()["pending"], [])
            after = c.db.query("SELECT * FROM bills ORDER BY sequence")
            self.assertEqual([{k: r[k] for k in before[0]} for r in after], before)
            self.assertEqual({k: [r.get(k) for r in after] for k in ("supplier_invoice_id", "correction_id")},
                             {"supplier_invoice_id": [None] * 3, "correction_id": [None] * 3})
            self.assertEqual({t: c.db.scalar(f"SELECT COUNT(*) FROM {t}") for t in counts}, counts)
            self.assertEqual(c.db.query("PRAGMA foreign_key_check"), [])
            self.assertEqual(c.db.scalar("PRAGMA defer_foreign_keys"), 0)
            # the rebuild drops the old table's triggers with it: every one of them must be recreated
            rebuilt = {r["name"] for r in c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='bills'")}
            self.assertTrue(bill_triggers <= rebuilt, sorted(bill_triggers - rebuilt))
            self.assertTrue({"bills_supplier_invoice_fresh_approval", "bills_supplier_invoice_one_live_bill", "bills_supplier_invoice_from_matched_record"} <= rebuilt)
            self.assertIn("corrected", c.db.scalar("SELECT sql FROM sqlite_master WHERE type='table' AND name='bills'"))
            for sql in ("UPDATE bills SET amount_due='1.00' WHERE id=?", "UPDATE bills SET status='void' WHERE id=?"):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):  # the recreated guards hold
                    c.db.execute(sql, (b2["id"],))
            self.assertEqual(c.bills.get(b1["id"])["status"], "paid")
            # the rebuilt table admits the governed correction of the latest unpaid bill
            c.bills.void(draft["id"], actor="pm", reason="not needed")
            c.bills.prepare_correction(b2["id"], "re-measure after upgrade (synthetic)", "accountant")
            res = c.execute(granted(c, "bill.correct", b2["id"])["id"], actor="accountant", period_id="P1")
            self.assertEqual(res.result["status"], "corrected")
            self.assertEqual([str(c.ledger.balance(a)) for a in ("5000", "1300", "2050")], ["20000.00", "10000.00", "3000.00"])
            for rec in (c.bills.ap_open_items(), c.bills.retainage_open_items(), c.bills.stored_material_items()):
                self.assertTrue(rec["reconciled"], rec)
            self.assertEqual(c.db.migrate(), [])
            self.assertTrue(c.ledger.trial_balance()["balanced"])
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            upgraded.db.close()


if __name__ == "__main__":
    unittest.main()
