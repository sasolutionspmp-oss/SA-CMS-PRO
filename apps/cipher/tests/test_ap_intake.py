"""Supplier invoice intake, duplicate detection and the 3-way match (ap_intake), with the
supplier-invoice link on bills and the bill.approve binding it.

Cost codes and specification sections are original placeholders ("XX 10 00"), never real
classification numbers."""
import datetime as _dt
import json
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.ids import sha256_hex, utcnow
from apps.cipher.domain.ap_intake import (
    EXCEPTION_CODES, PLUGIN_NAME, SCHEMA_NAME, APIntakeError, DuplicateInvoiceError, InvoiceIneligible, normalize_invoice_number,
)
from apps.cipher.domain.bills import BillError, BillIneligible
from apps.cipher.service import Cipher

ENTITY = "S&A Solutions LLC (synthetic)"
FUTURE = "2099-12-31"


def today() -> str:
    return utcnow().date().isoformat()


def lines_of(journal):
    return [(ln["account_code"], ln["debit"], ln["credit"]) for ln in journal["lines"]]


class World:
    """A verified sheet-pile subcontractor, a cofferdam project, open period P1 and an executed
    60,000 + 40,000 subcontract at 10% retainage."""

    def __init__(self):
        c = self.c = Cipher()
        self.ap = c.plugin(PLUGIN_NAME)
        sup = c.add_party(kind="supplier", name="Synthetic sheet pile subcontractor", destination="ACH-SIM-AP-0001")
        self.supplier = c.verify_destination(sup["id"], destination="ACH-SIM-AP-0001", verified_by="owner")
        other = c.add_party(kind="supplier", name="Synthetic dewatering subcontractor", destination="ACH-SIM-AP-0002")
        self.other_supplier = c.verify_destination(other["id"], destination="ACH-SIM-AP-0002", verified_by="owner")
        self.customer = c.add_party(kind="customer", name="Synthetic owner agency")
        self.project = c.create_project(name="Synthetic cofferdam and dewatering", entity=ENTITY, budget="250000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.cid = self.commitment("60000", "40000")
        self._pdf = 0

    def commitment(self, *amounts, rate="0.10", supplier_id=None):
        cmt = self.c.commitments.create(
            project_id=self.pid, supplier_id=supplier_id or self.supplier["id"], title="Synthetic sheet pile subcontract",
            sov_lines=[{"description": f"Scope {i}", "amount": a, "cost_code": f"XX {i}0 00"} for i, a in enumerate(amounts, start=1)],
            retainage_rate=rate, actor="pm",
        )
        self.c.approve_and_execute("commitment.execute", cmt["id"], actor_role="pm")
        return cmt["id"]

    def line(self, n, cid=None):
        return self.c.commitments.get(cid or self.cid)["sov"][n - 1]["id"]

    def pdf(self, label=None, *, kind="supplier_invoice", project_id=None):
        self._pdf += 1
        label = label or f"invoice pdf {self._pdf}"
        doc = self.c.evidence.register_document(project_id=project_id or self.pid, kind=kind, title=f"Supplier invoice PDF: {label}", actor="ap clerk")
        rev = self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic supplier invoice {self._pdf}: {label}".encode(), actor="ap clerk")
        return doc, rev

    def revise_pdf(self, doc, label):
        return self.c.evidence.add_revision(document_id=doc["id"], content=f"synthetic supplier invoice reissued: {label}".encode(), actor="ap clerk")

    def receive(self, number, amount, *, invoice_date="2026-10-15", commitment=True, supplier_id=None, evidence=None, **kw):
        if evidence is None:
            _, rev = self.pdf(number)
            evidence = rev["content_hash"]
        cid = kw.pop("commitment_id", self.cid if commitment else None)
        return self.ap.receive_invoice(supplier_id or self.supplier["id"], number, invoice_date, amount, evidence, "ap clerk",
                                       project_id=self.pid, commitment_id=cid, **kw)

    def certify(self, installed, *, cid=None):
        return self.c.bills.certify(commitment_id=cid or self.cid, period_id="P1",
                                    installed=[{"sov_line_id": self.line(n, cid), "cumulative_installed": v} for n, v in installed.items()], actor="pm")

    def request_match(self, invoice_id):
        ap = self.c.request_approval("ap_intake.match_invoice", invoice_id, actor_role="accountant", requested_by="ap clerk")
        self.c.approve(ap["id"], approver="controller", approver_role="controller")
        return ap

    def execute(self, approval_id, **kw):
        return self.c.execute(approval_id, actor="accountant", **kw)

    def match_and_execute(self, invoice_id):
        res = self.ap.match(invoice_id, "ap clerk")
        assert res["status"] == "matched", res
        return self.execute(self.request_match(invoice_id)["id"])

    def post(self, bill_id):
        ap = self.c.request_approval("bill.approve", bill_id, actor_role="accountant", requested_by="pm")
        self.c.approve(ap["id"], approver="controller", approver_role="controller")
        return self.c.post_bill(bill_id, actor="accountant")

    def assert_books(self, tc):
        c = self.c
        tc.assertTrue(c.ledger.trial_balance()["balanced"])
        tc.assertTrue(c.audit.verify_chain()["ok"])
        for rec in (c.bills.ap_open_items(), c.bills.ap_open_items(self.pid), c.bills.retainage_open_items(), c.bills.stored_material_items()):
            tc.assertTrue(rec["reconciled"], rec)


# --------------------------------------------------------------------------- #
# 1. intake validation                                                         #
# --------------------------------------------------------------------------- #

class IntakeTests(unittest.TestCase):
    def test_plugin_registers_its_schema_and_codes(self):
        w = World()
        names = {r["name"] for r in w.c.db.query("SELECT name FROM schema_version")}
        self.assertIn(SCHEMA_NAME, names)
        self.assertEqual(EXCEPTION_CODES, ("amount_mismatch", "not_received", "damaged_receipt", "no_certified_bill", "possible_duplicate",
                                           "evidence_stale", "over_commitment"))
        self.assertEqual(w.c.project_state(w.pid)[PLUGIN_NAME]["summary"]["invoices"], 0)
        self.assertIn("ap_intake", w.c.audit_export()["modules"])

    def test_receive_records_the_invoice_with_its_evidence_and_default_due_date(self):
        w = World()
        doc, rev = w.pdf("SP-1001")
        inv = w.receive("SP-1001", "27000.00", evidence=rev["content_hash"], service_period_start="2026-10-01", service_period_end="2026-10-31",
                        lines=[{"description": "Sheet piling installed", "quantity": "300", "unit_price": "90", "amount": "27000.00", "sov_line_id": w.line(1)}])
        self.assertEqual((inv["status"], inv["version"], inv["amount"], inv["invoice_date"], inv["due_date"], inv["terms_days"]),
                         ("received", 1, "27000.00", "2026-10-15", "2026-11-14", 30))
        self.assertEqual((inv["evidence_document_id"], inv["evidence_revision_id"], inv["evidence_hash"], inv["evidence_current"]),
                         (doc["id"], rev["id"], rev["content_hash"], True))
        self.assertEqual((inv["number_key"], inv["possible_duplicate"], inv["match_status"], inv["service_period_start"]), ("sp1001", False, None, "2026-10-01"))
        self.assertEqual(inv["lines"], [{"line_no": 1, "description": "Sheet piling installed", "quantity": "300", "unit_price": "90", "amount": "27000.00",
                                         "sov_line_id": w.line(1), "equipment_id": None}])
        received = [e for e in w.c.audit.entries(entity_type="ap_invoice", entity_id=inv["id"]) if e["action"] == "ap_intake.invoice_received"]
        self.assertEqual(len(received), 1)
        # payment terms per supplier, and an explicit due date
        self.assertEqual(w.ap.terms(w.supplier["id"]), 30)
        self.assertEqual(w.ap.set_terms(w.supplier["id"], 45, "controller"), {"supplier_id": w.supplier["id"], "days": 45, "version": 1})
        self.assertEqual(w.receive("SP-1002", "100.00", invoice_date="2026-10-20")["due_date"], "2026-12-04")
        self.assertEqual(w.ap.set_terms(w.supplier["id"], 10, "controller")["version"], 2)
        explicit = w.receive("SP-1003", "200.00", invoice_date="2026-10-20", due_date="2026-10-25")
        self.assertEqual((explicit["due_date"], explicit["terms_days"]), ("2026-10-25", None))
        for bad in (-1, 366, 1.5, True, "30"):
            with self.subTest(days=bad), self.assertRaises(APIntakeError):
                w.ap.set_terms(w.supplier["id"], bad, "controller")
        with self.assertRaises(APIntakeError):  # terms unchanged is a duplicate
            w.ap.set_terms(w.supplier["id"], 10, "controller")
        with self.assertRaises(APIntakeError):  # terms are for suppliers
            w.ap.set_terms(w.customer["id"], 30, "controller")
        self.assertTrue(w.c.audit.verify_chain()["ok"])

    def test_invalid_input_is_refused(self):
        w = World()
        drawing_doc, drawing = w.pdf("drawing", kind="drawing")
        other_project = w.c.create_project(name="Another synthetic project", entity=ENTITY, budget="1000")
        _, foreign = w.pdf("foreign", project_id=other_project["id"])
        doc, rev1 = w.pdf("SP-2000")
        rev2 = w.revise_pdf(doc, "SP-2000 corrected")
        good = rev2["content_hash"]
        other_cid = w.commitment("5000", supplier_id=w.other_supplier["id"])
        cases = [
            ("float amount", dict(amount=27000.0)),
            ("zero amount", dict(amount="0")),
            ("negative amount", dict(amount="-5.00")),
            ("sub-cent amount", dict(amount="10.005")),
            ("not a number", dict(amount="abc")),
            ("bad date", dict(invoice_date="2026-13-01")),
            ("bad date format", dict(invoice_date="15/10/2026")),
            ("due before invoice", dict(due_date="2026-10-01")),
            ("half service period", dict(service_period_start="2026-10-01")),
            ("service period backwards", dict(service_period_start="2026-10-31", service_period_end="2026-10-01")),
            ("empty number", dict(number="   ")),
            ("punctuation-only number", dict(number="--/--")),
            ("quoted number", dict(number='SP-"2000"')),
            ("unknown evidence", dict(evidence=sha256_hex(b"a hash Cipher never stored"))),
            ("evidence of another kind", dict(evidence=drawing["content_hash"])),
            ("evidence on another project", dict(evidence=foreign["content_hash"])),
            ("superseded evidence", dict(evidence=rev1["content_hash"])),
            ("empty evidence", dict(evidence="")),
            ("another supplier's commitment", dict(commitment_id=other_cid)),
            ("unknown commitment", dict(commitment_id="cmt_missing")),
            ("customer as supplier", dict(supplier_id=w.customer["id"])),
            ("lines do not add up", dict(lines=[{"description": "Piling", "amount": "100.00"}])),
            ("quantity x price mismatch", dict(amount="900.00", lines=[{"description": "Piling", "quantity": "10", "unit_price": "91", "amount": "900.00"}])),
            ("quantity without price", dict(amount="900.00", lines=[{"description": "Piling", "quantity": "10", "amount": "900.00"}])),
            ("both references", dict(amount="900.00", lines=[{"description": "Piling", "amount": "900.00", "sov_line_id": w.line(1), "equipment_id": "peq_x"}])),
            ("SOV line of another commitment", dict(amount="900.00", lines=[{"description": "Piling", "amount": "900.00", "sov_line_id": w.line(1, other_cid)}])),
            ("unknown line field", dict(amount="900.00", lines=[{"description": "Piling", "amount": "900.00", "tax": "1"}])),
            ("line without description", dict(amount="900.00", lines=[{"amount": "900.00"}])),
            ("lines not a list", dict(lines="Piling 900")),
        ]
        for label, kw in cases:
            kw = dict(kw)
            number = kw.pop("number", "SP-2000")
            amount = kw.pop("amount", "900.00")
            evidence = kw.pop("evidence", good)
            with self.subTest(case=label), self.assertRaises(APIntakeError):
                w.receive(number, amount, evidence=evidence, **kw)
        with self.assertRaises(APIntakeError):  # unknown project
            w.ap.receive_invoice(w.supplier["id"], "SP-2000", "2026-10-15", "900.00", good, "ap clerk", project_id="prj_missing")
        with self.assertRaises(APIntakeError):  # an actor is required
            w.ap.receive_invoice(w.supplier["id"], "SP-2000", "2026-10-15", "900.00", good, " ", project_id=w.pid)
        with self.assertRaises(APIntakeError):  # an SOV line needs the commitment it belongs to
            w.receive("SP-2000", "900.00", evidence=good, commitment=False, lines=[{"description": "Piling", "amount": "900.00", "sov_line_id": w.line(1)}])
        self.assertEqual(w.ap.invoices(), [])
        inv = w.receive("SP-2000", "900.00", evidence=good)
        with self.assertRaises(APIntakeError):  # one document backs one invoice
            w.receive("SP-2001", "900.00", evidence=good)
        self.assertEqual([i["id"] for i in w.ap.invoices(w.pid)], [inv["id"]])
        self.assertEqual(drawing_doc["kind"], "drawing")

    def test_storage_guards(self):
        w = World()
        inv = w.receive("SP-3000", "500.00")
        for sql in ("UPDATE ap_invoices SET amount='5000.00' WHERE id=?",
                    "UPDATE ap_invoices SET status='matched' WHERE id=?",
                    "UPDATE ap_invoices SET supplier_id='pty_other' WHERE id=?",
                    "UPDATE ap_invoices SET possible_duplicate=1 WHERE id=?",
                    "DELETE FROM ap_invoices WHERE id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                w.c.db.execute(sql, (inv["id"],))
        row = w.c.db.one("SELECT * FROM ap_invoices WHERE id=?", (inv["id"],))
        clone = dict(row, id="apinv_raw_clone", evidence_document_id=row["evidence_document_id"])
        cols = ", ".join(clone)
        with self.assertRaises(sqlite3.DatabaseError):  # same supplier and number, by raw SQL too
            w.c.db.execute(f"INSERT INTO ap_invoices ({cols}) VALUES ({', '.join('?' * len(clone))})", tuple(clone.values()))
        res = w.ap.match(inv["id"], "ap clerk")
        with self.assertRaises(sqlite3.DatabaseError):  # the computation log is append-only
            w.c.db.execute("UPDATE ap_invoice_matches SET status='matched' WHERE id=?", (res["attempt_id"],))
        self.assertEqual(w.ap.invoice(inv["id"])["amount"], "500.00")


# --------------------------------------------------------------------------- #
# 2. duplicates                                                                #
# --------------------------------------------------------------------------- #

class DuplicateTests(unittest.TestCase):
    def test_same_supplier_and_normalized_number_is_refused(self):
        w = World()
        first = w.receive("INV-0042", "1000.00")
        for variant in ("inv 0042", "Inv/0042", " INV.0042 ", "INV_0042"):
            with self.subTest(number=variant), self.assertRaises(DuplicateInvoiceError):
                w.receive(variant, "1234.00", invoice_date="2026-08-01")
        self.assertEqual(normalize_invoice_number("Inv/0042"), "inv0042")
        # another supplier may use the same number
        other = w.receive("INV-0042", "1000.00", supplier_id=w.other_supplier["id"], commitment=False)
        self.assertFalse(other["possible_duplicate"])
        # a rejected invoice keeps its number taken
        w.ap.reject_invoice(first["id"], "issued in error by the supplier", "ap clerk")
        with self.assertRaises(DuplicateInvoiceError):
            w.receive("INV-0042", "1000.00")
        with self.assertRaises(APIntakeError):  # rejected is final
            w.ap.revise_invoice(first["id"], "ap clerk", reason="retry", amount="1.00")

    def test_near_duplicate_is_flagged_and_blocks_matching_until_cleared(self):
        w = World()
        bill = w.certify({1: "30000"})  # 27,000 due
        a = w.receive("SP-5001", "27000.00", invoice_date="2026-10-10")
        b = w.receive("SP-5002", "27000.00", invoice_date="2026-10-16")  # 6 days later, same amount
        far = w.receive("SP-5003", "27000.00", invoice_date="2026-10-18")  # 8 days after a, 2 after b
        apart = w.receive("SP-5004", "27000.00", invoice_date="2026-10-30")  # 12 days after far
        other_amount = w.receive("SP-5005", "26000.00", invoice_date="2026-10-30")
        self.assertEqual((a["possible_duplicate"], b["possible_duplicate"], b["duplicate_of"]), (False, True, [a["id"]]))
        self.assertEqual(sorted(far["duplicate_of"]), [b["id"]])
        self.assertEqual((apart["possible_duplicate"], other_amount["possible_duplicate"]), (False, False))

        res = w.ap.match(b["id"], "ap clerk")
        self.assertEqual((res["status"], res["exceptions"], res["bill"]["id"]), ("exception", ["possible_duplicate"], bill["id"]))
        with self.assertRaises(InvoiceIneligible):
            w.c.request_approval("ap_intake.match_invoice", b["id"], actor_role="accountant")
        with self.assertRaises(APIntakeError):
            w.ap.clear_duplicate_flag(a["id"], "not flagged", "ap clerk")
        with self.assertRaises(APIntakeError):
            w.ap.clear_duplicate_flag(b["id"], "  ", "ap clerk")
        cleared = w.ap.clear_duplicate_flag(b["id"], "called the supplier: SP-5001 was a pro-forma, SP-5002 is the invoice", "controller")
        self.assertEqual((cleared["possible_duplicate"], cleared["duplicate_blocking"], cleared["duplicate_cleared_by"]), (True, False, "controller"))
        with self.assertRaises(APIntakeError):  # cleared once
            w.ap.clear_duplicate_flag(b["id"], "again", "controller")
        w.ap.reject_invoice(a["id"], "pro-forma, not an invoice", "ap clerk")
        out = w.match_and_execute(b["id"])
        self.assertEqual((out.result["status"], out.result["bill"]), ("matched", bill["id"]))
        self.assertEqual(w.ap.invoice(b["id"])["status"], "matched")
        self.assertEqual([e["action"] for e in w.c.audit.entries(entity_type="ap_invoice", entity_id=b["id"])][:2],
                         ["ap_intake.invoice_received", "ap_intake.match_computed"])
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 3. progress-subcontract match                                                #
# --------------------------------------------------------------------------- #

class ProgressMatchTests(unittest.TestCase):
    def test_progress_invoice_matches_its_certified_bill_and_links_it(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        self.assertEqual((bill["cumulative_gross"], bill["cumulative_retainage"], bill["amount_due"]), ("30000.00", "3000.00", "27000.00"))
        inv = w.receive("SP-1001", "27000.00", invoice_date="2026-10-20")
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual((res["basis"], res["status"], res["exceptions"], res["matched_amount"]), ("progress", "matched", [], "27000.00"))
        self.assertEqual((res["bill"]["id"], res["bill"]["status"], res["bill"]["content_hash"]), (bill["id"], "draft", bill["content_hash"]))
        state = c.project_state(w.pid)[PLUGIN_NAME]
        self.assertEqual((state["summary"]["received"], state["invoices"][0]["match_status"], state["invoices"][0]["latest_match"]["id"]),
                         (1, "matched", res["attempt_id"]))

        ap = c.request_approval("ap_intake.match_invoice", inv["id"], actor_role="accountant", requested_by="ap clerk")
        m = ap["manifest"]
        self.assertEqual((m["subject"], m["amounts"], m["entity"], m["currency"]),
                         ({"type": "ap_invoice", "id": inv["id"]}, {"invoice_amount": "27000.00", "matched_amount": "27000.00"}, ENTITY, "USD"))
        b = m["bindings"]
        self.assertEqual((b["invoice_hash"], b["evidence_hash"], b["evidence_current_hash"], b["due_date"], b["bill"]["id"], b["bill"]["content_hash"],
                          b["match_attempt_id"], b["result_hash"]),
                         (inv["content_hash"], inv["evidence_hash"], inv["evidence_hash"], "2026-11-19", bill["id"], bill["content_hash"],
                          res["attempt_id"], res["result_hash"]))
        self.assertEqual(m["destination"], {"party_id": w.supplier["id"], "destination": "ACH-SIM-AP-0001", "destination_version": w.supplier["destination_version"]})
        with self.assertRaises(PermissionError):  # roles: a PM does not hold the authority
            c.request_approval("ap_intake.match_invoice", inv["id"], actor_role="pm")
        with self.assertRaises(PermissionError):
            c.approve(ap["id"], approver="pm", approver_role="pm")
        c.approve(ap["id"], approver="controller", approver_role="controller")
        out = w.execute(ap["id"])
        self.assertEqual(out.result, {"invoice": inv["id"], "status": "matched", "basis": "progress", "bill": bill["id"], "receipts": [],
                                      "amount": "27000.00", "due_date": "2026-11-19"})
        self.assertTrue(w.execute(ap["id"]).replayed)  # replay: one effect
        linked = c.bills.get(bill["id"])
        self.assertEqual((linked["supplier_invoice_id"], linked["supplier_invoice_number"], linked["invoice_date"], linked["due_date"],
                          linked["supplier_invoice_hash"], linked["supplier_invoice_approval_id"]),
                         (inv["id"], "SP-1001", "2026-10-20", "2026-11-19", inv["content_hash"], ap["id"]))
        matched = w.ap.invoice(inv["id"])
        self.assertEqual((matched["status"], matched["matched_bill_id"], matched["matched_commitment_id"], matched["match_approval_id"]),
                         ("matched", bill["id"], w.cid, ap["id"]))
        with self.assertRaises(APIntakeError):  # matched once
            w.ap.match(inv["id"], "ap clerk")
        with self.assertRaises(APIntakeError):  # a matched invoice is not rejected
            w.ap.reject_invoice(inv["id"], "changed mind", "ap clerk")

        # bill.approve binds the attached invoice; posting writes the approved journal
        bap = c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        si = bap["manifest"]["bindings"]["supplier_invoice"]
        self.assertEqual((si["id"], si["number"], si["evidence_hash"], si["invoice_hash"], si["due_date"]),
                         (inv["id"], "SP-1001", inv["evidence_hash"], inv["content_hash"], "2026-11-19"))
        c.approve(bap["id"], approver="controller", approver_role="controller")
        w.c.post_bill(bill["id"], actor="accountant")
        self.assertEqual([lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=bill["id"])],
                         [[("5000", "30000.00", "0.00"), ("2000", "0.00", "27000.00"), ("2050", "0.00", "3000.00")]])
        ap_items = c.bills.ap_open_items(w.pid)
        item = next(i for i in ap_items["items"] if i["bill_id"] == bill["id"])
        self.assertEqual((item["open"], item["due_date"], item["due_date_basis"], item["supplier_invoice_number"], item["invoice_date"]),
                         ("27000.00", "2026-11-19", "supplier_invoice", "SP-1001", "2026-10-20"))
        self.assertEqual((ap_items["subledger_total"], ap_items["control_balance"], ap_items["reconciled"]), ("27000.00", "27000.00", True))
        w.assert_books(self)

    def test_progress_exceptions(self):
        w = World()
        c = w.c
        # no commitment named (same-amount invoices are dated weeks apart: no near duplicates here)
        loose = w.receive("SP-9001", "27000.00", commitment=False, invoice_date="2026-09-01")
        self.assertEqual(w.ap.match(loose["id"], "ap clerk")["exceptions"], ["no_certified_bill"])
        # a commitment with no certified bill
        inv = w.receive("SP-9002", "27000.00", invoice_date="2026-10-01")
        self.assertEqual(w.ap.match(inv["id"], "ap clerk")["exceptions"], ["no_certified_bill"])
        bill = w.certify({1: "30000"})
        # an amount that matches no bill exactly (tolerance 0.00)
        short = w.receive("SP-9003", "26999.99")
        res = w.ap.match(short["id"], "ap clerk")
        self.assertEqual((res["status"], res["exceptions"]), ("exception", ["amount_mismatch"]))
        self.assertIn("bill 1 due 27000.00", res["details"][0]["detail"])
        # the invoice PDF gained a newer revision
        doc, rev = w.pdf("SP-9004")
        stale = w.receive("SP-9004", "27000.00", evidence=rev["content_hash"], invoice_date="2026-10-20")
        w.revise_pdf(doc, "SP-9004 reissued")
        res = w.ap.match(stale["id"], "ap clerk")
        self.assertEqual(res["exceptions"], ["evidence_stale"])
        with self.assertRaises(InvoiceIneligible):
            c.request_approval("ap_intake.match_invoice", stale["id"], actor_role="accountant")
        # the commitment's bill is stale after a change: not a certified bill free for the invoice
        ch = c.commitments.propose_change(w.cid, amount="5000", reason="extra piling (synthetic)", sov_line_id=w.line(2), actor="pm")
        c.approve_and_execute("change.execute", ch["id"], actor_role="pm")
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual(res["exceptions"], ["no_certified_bill"])
        self.assertIn("stale", res["details"][0]["detail"])
        c.bills.void(bill["id"], actor="pm", reason="re-certify after the change")
        fresh = w.certify({1: "30000"})
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual((res["status"], res["bill"]["id"]), ("matched", fresh["id"]))
        # every exception computation is on record
        self.assertEqual([a["status"] for a in c.db.query("SELECT status FROM ap_invoice_matches WHERE invoice_id=? ORDER BY rowid", (inv["id"],))],
                         ["exception", "exception", "matched"])
        self.assertEqual(c.project_state(w.pid)[PLUGIN_NAME]["summary"]["exceptions"], 3)  # loose, short, stale
        w.assert_books(self)

    def test_match_approval_goes_stale_when_the_bill_or_invoice_changes(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-7001", "27000.00")
        w.ap.match(inv["id"], "ap clerk")
        ap = w.request_match(inv["id"])
        # the bill changes: voided and re-certified (a new bill, the same amount)
        c.bills.void(bill["id"], actor="pm", reason="re-measured")
        replacement = w.certify({1: "30000"})
        with self.assertRaises(StaleApprovalError):
            w.execute(ap["id"])
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual((w.ap.invoice(inv["id"])["status"], c.bills.get(replacement["id"])["supplier_invoice_id"]), ("received", None))
        with self.assertRaises(InvoiceIneligible):  # the recorded match no longer equals a fresh one
            c.request_approval("ap_intake.match_invoice", inv["id"], actor_role="accountant")

        # the bill changes state: posted after the match approval was granted
        w.ap.match(inv["id"], "ap clerk")
        ap2 = w.request_match(inv["id"])
        w.post(replacement["id"])
        with self.assertRaises(StaleApprovalError):
            w.execute(ap2["id"])
        self.assertEqual(c.approvals.get(ap2["id"])["status"], "invalidated")

        # the invoice changes: a revision invalidates the open approval at once
        w.ap.match(inv["id"], "ap clerk")
        ap3 = w.request_match(inv["id"])
        revised = w.ap.revise_invoice(inv["id"], "ap clerk", reason="supplier corrected the due date", due_date="2026-11-30")
        self.assertEqual((revised["version"], revised["status"], revised["match_status"], revised["due_date"]), (2, "received", None, "2026-11-30"))
        self.assertEqual(c.approvals.get(ap3["id"])["status"], "invalidated")
        with self.assertRaises((ApprovalNotGranted, StaleApprovalError)):
            w.execute(ap3["id"])
        with self.assertRaises(APIntakeError):  # a revision must change something
            w.ap.revise_invoice(inv["id"], "ap clerk", reason="nothing", due_date="2026-11-30")

        # the invoice PDF gains a newer revision after approval: execution finds evidence_stale
        w.ap.match(inv["id"], "ap clerk")
        ap4 = w.request_match(inv["id"])
        w.revise_pdf(c.db.one("SELECT * FROM documents WHERE id=?", (revised["evidence_document_id"],)), "SP-7001 reissued")
        with self.assertRaises(StaleApprovalError):
            w.execute(ap4["id"])
        self.assertEqual(c.approvals.get(ap4["id"])["status"], "invalidated")

        # a payee destination change invalidates a granted match approval too
        doc_id = revised["evidence_document_id"]
        current = c.evidence.current_revision(doc_id)
        w.ap.revise_invoice(inv["id"], "ap clerk", reason="bind the reissued PDF", evidence_hash=current["content_hash"])
        w.ap.match(inv["id"], "ap clerk")
        ap5 = w.request_match(inv["id"])
        c.verify_destination(w.supplier["id"], destination="ACH-SIM-AP-0001-B", verified_by="bank admin")
        self.assertEqual(c.approvals.get(ap5["id"])["status"], "invalidated")

        # finally a fresh computation and approval execute once
        w.ap.match(inv["id"], "ap clerk")
        ap6 = w.request_match(inv["id"])
        self.assertEqual(w.execute(ap6["id"]).result["bill"], replacement["id"])
        self.assertEqual(c.bills.get(replacement["id"])["supplier_invoice_number"], "SP-7001")
        w.assert_books(self)

    def test_nothing_links_a_bill_without_the_consumed_match_approval(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-6001", "27000.00")
        w.ap.match(inv["id"], "ap clerk")
        with self.assertRaises(APIntakeError):  # apply refuses an approval it was not given
            w.ap.apply("ap_intake.match_invoice", inv["id"], approval_id="apr_forged", manifest={"bindings": {}}, actor="accountant", period_id=None)
        with self.assertRaises(BillError):  # no consumed match approval: the bill cannot be linked directly
            c.bills.attach_supplier_invoice(bill["id"], {"id": inv["id"], "invoice_number": "SP-6001", "invoice_date": inv["invoice_date"],
                                                         "due_date": inv["due_date"], "content_hash": inv["content_hash"], "evidence_hash": inv["evidence_hash"],
                                                         "supplier_id": w.supplier["id"], "project_id": w.pid, "amount": "27000.00",
                                                         "match_approval_id": "apr_forged"}, "accountant")
        with self.assertRaises(sqlite3.DatabaseError):  # nor by raw SQL
            c.db.execute("UPDATE bills SET supplier_invoice_id=?, supplier_invoice_number='SP-6001', invoice_date='2026-10-15', due_date='2026-11-14', "
                         "supplier_invoice_hash='x', supplier_invoice_evidence_hash='y', supplier_invoice_approval_id=NULL WHERE id=?", (inv["id"], bill["id"]))
        self.assertIsNone(c.bills.get(bill["id"])["supplier_invoice_id"])
        w.match_and_execute(inv["id"])
        for sql in ("UPDATE bills SET supplier_invoice_number='SP-6001-X' WHERE id=?",   # every linked field follows the audited attachment
                    "UPDATE bills SET due_date='2027-01-31' WHERE id=?",
                    "UPDATE bills SET supplier_invoice_id=NULL WHERE id=?"):             # and the link is never removed
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (bill["id"],))
        self.assertEqual((c.bills.get(bill["id"])["supplier_invoice_number"], c.bills.get(bill["id"])["due_date"]), ("SP-6001", inv["due_date"]))


# --------------------------------------------------------------------------- #
# 4. purchase-order match                                                      #
# --------------------------------------------------------------------------- #

class PurchaseOrderWorld(World):
    """Two pumps awarded at 58,000 (29,000 each on the drafted PO), the PO executed."""

    def __init__(self, *, execute_po=True):
        super().__init__()
        c = self.c
        self.p = c.plugin("procurement")
        self.e1 = self.p.add_equipment(self.pid, "P-101", "Dewatering pump", "XX 21 13", "2027-03-01", long_lead=True, actor="pm")
        self.e2 = self.p.add_equipment(self.pid, "P-102", "Dewatering pump (standby)", "XX 21 13", "2027-04-01", long_lead=True, actor="pm")
        req = self.p.create_requisition(self.pid, "Dewatering pumps", [self.e1["id"], self.e2["id"]], actor="pm")
        q = self.p.add_quote(req["id"], self.supplier["id"], "58000.00", 20, FUTURE, True, actor="buyer")
        self.p.select_quote(req["id"], q["id"], "", actor="pm")
        self.award = c.approve_and_execute("procurement.award", req["id"], actor_role="pm", period_id="P1").result
        self.po = self.award["commitment"]
        if execute_po:
            c.approve_and_execute("commitment.execute", self.po, actor_role="pm")

    def receive_equipment(self, equipment, condition="ok"):
        return self.p.receive(equipment["id"], today(), condition, sha256_hex(f"delivery ticket {equipment['tag']}".encode()), actor="field")

    def po_invoice(self, number, *items, invoice_date, commitment=True):
        """Same-amount invoices in one test are dated weeks apart so none is a near duplicate."""
        lines = [{"description": f"{eq['tag']} supplied", "amount": amt, "equipment_id": eq["id"]} for eq, amt in items]
        total_amount = f"{sum((Decimal(a) for _, a in items), Decimal('0.00')):f}"
        return self.receive(number, total_amount, invoice_date=invoice_date, commitment_id=self.po if commitment else None, lines=lines)


class PurchaseOrderMatchTests(unittest.TestCase):
    def test_po_invoice_matches_received_equipment_and_records_receipts(self):
        w = PurchaseOrderWorld()
        c = w.c
        self.assertEqual(self.sov_amounts(w), ["29000.00", "29000.00"])
        r1 = w.receive_equipment(w.e1)
        inv = w.po_invoice("PO-INV-1", (w.e1, "29000.00"), invoice_date="2026-09-01")
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual((res["basis"], res["status"], res["exceptions"], res["matched_amount"], res["bill"]), ("purchase_order", "matched", [], "29000.00", None))
        self.assertEqual([(r["receipt_id"], r["condition"]) for r in res["receipts"]], [(r1["id"], "ok")])
        self.assertEqual(res["po_lines"][0]["po_amount"], "29000.00")
        ap = w.request_match(inv["id"])
        self.assertEqual([r["receipt_id"] for r in ap["manifest"]["bindings"]["receipts"]], [r1["id"]])
        out = w.execute(ap["id"])
        self.assertEqual((out.result["basis"], out.result["receipts"], out.result["bill"]), ("purchase_order", [r1["id"]], None))
        self.assertEqual(w.ap.invoice(inv["id"])["matched_commitment_id"], w.po)
        # the same equipment cannot be invoiced again
        again = w.po_invoice("PO-INV-2", (w.e1, "29000.00"), invoice_date="2026-09-20")
        res = w.ap.match(again["id"], "ap clerk")
        self.assertEqual(res["exceptions"], ["over_commitment"])
        self.assertIn("already invoiced on PO-INV-1", res["details"][0]["detail"])
        # equipment found through the lines when the invoice names no commitment
        w.receive_equipment(w.e2)
        loose = w.po_invoice("PO-INV-3", (w.e2, "29000.00"), invoice_date="2026-10-10", commitment=False)
        res = w.ap.match(loose["id"], "ap clerk")
        self.assertEqual((res["basis"], res["status"], res["commitment"]["id"]), ("purchase_order", "matched", w.po))
        w.assert_books(self)

    @staticmethod
    def sov_amounts(w):
        return [s["amount"] for s in w.c.commitments.get(w.po)["sov"]]

    def test_po_exception_codes(self):
        w = PurchaseOrderWorld()
        # not received
        inv = w.po_invoice("PO-X-1", (w.e1, "29000.00"), invoice_date="2026-07-01")
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual(res["exceptions"], ["not_received"])
        with self.assertRaises(InvoiceIneligible):
            w.c.request_approval("ap_intake.match_invoice", inv["id"], actor_role="accountant")
        # damaged receipt
        w.receive_equipment(w.e2, condition="damaged")
        damaged = w.po_invoice("PO-X-2", (w.e2, "29000.00"), invoice_date="2026-07-15")
        self.assertEqual(w.ap.match(damaged["id"], "ap clerk")["exceptions"], ["damaged_receipt"])
        # received now: the same invoice matches
        w.receive_equipment(w.e1)
        self.assertEqual(w.ap.match(inv["id"], "ap clerk")["status"], "matched")
        # amount mismatch: a line that differs from its PO line (tolerance 0.00)
        dear = w.po_invoice("PO-X-3", (w.e1, "29000.01"), invoice_date="2026-07-30")
        res = w.ap.match(dear["id"], "ap clerk")
        self.assertEqual(res["exceptions"], ["amount_mismatch"])
        # a line without equipment on a PO invoice
        blank = w.receive("PO-X-4", "100.00", invoice_date="2026-07-30", commitment_id=w.po, lines=[{"description": "freight", "amount": "100.00"}])
        self.assertEqual(w.ap.match(blank["id"], "ap clerk")["exceptions"], ["amount_mismatch", "not_received"])
        # no lines at all
        bare = w.receive("PO-X-5", "29000.00", invoice_date="2026-08-15", commitment_id=w.po)
        self.assertEqual(w.ap.match(bare["id"], "ap clerk")["exceptions"], ["not_received"])
        # equipment that is not on this purchase order
        other_eq = w.p.add_equipment(w.pid, "P-201", "Sump pump", "XX 21 13", "2027-05-01", actor="pm")
        stray = w.receive("PO-X-6", "29000.00", invoice_date="2026-09-01", commitment_id=w.po,
                          lines=[{"description": "sump pump", "amount": "29000.00", "equipment_id": other_eq["id"]}])
        self.assertEqual(w.ap.match(stray["id"], "ap clerk")["exceptions"], ["amount_mismatch", "over_commitment"])
        self.assertEqual([i["possible_duplicate"] for i in w.ap.invoices(w.pid)], [False] * 6)
        w.assert_books(self)

    def test_unexecuted_po_is_over_commitment_and_a_certified_po_bill_is_linked(self):
        w = PurchaseOrderWorld(execute_po=False)
        c = w.c
        w.receive_equipment(w.e1)
        inv = w.po_invoice("PO-D-1", (w.e1, "29000.00"), invoice_date=today())
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual(res["exceptions"], ["over_commitment"])
        self.assertIn("draft", res["details"][0]["detail"])
        c.approve_and_execute("commitment.execute", w.po, actor_role="pm")
        # a certified PO bill (retainage 0.00) for the received pump is linked by the match
        po_bill = c.bills.certify(commitment_id=w.po, period_id="P1",
                                  installed=[{"sov_line_id": c.commitments.get(w.po)["sov"][0]["id"], "cumulative_installed": "29000"}], actor="pm")
        self.assertEqual(po_bill["amount_due"], "29000.00")
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual((res["status"], res["basis"], res["bill"]["id"]), ("matched", "purchase_order", po_bill["id"]))
        w.execute(w.request_match(inv["id"])["id"])
        self.assertEqual(c.bills.get(po_bill["id"])["supplier_invoice_number"], "PO-D-1")
        w.post(po_bill["id"])
        self.assertEqual([lines_of(j) for j in c.ledger.journals(source_type="bill", source_id=po_bill["id"])],
                         [[("5000", "29000.00", "0.00"), ("2000", "0.00", "29000.00")]])
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 5. bill.approve binds the supplier invoice                                   #
# --------------------------------------------------------------------------- #

class BillApproveInvoiceBindingTests(unittest.TestCase):
    def test_bill_approval_goes_stale_when_the_invoice_is_replaced(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        doc, rev = w.pdf("SP-8001")
        inv = w.receive("SP-8001", "27000.00", evidence=rev["content_hash"])
        early = c.request_approval("bill.approve", bill["id"], actor_role="accountant")  # requested before the invoice is attached
        w.match_and_execute(inv["id"])
        self.assertEqual(c.approvals.get(early["id"])["status"], "invalidated")

        bap = c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        c.approve(bap["id"], approver="controller", approver_role="controller")
        # the supplier reissues the invoice: a new revision of its PDF, bound by a revision of the invoice
        rev2 = w.revise_pdf(doc, "SP-8001 reissued with the correct bank remittance block")
        with self.assertRaises(StaleApprovalError):  # the PDF alone already makes the approval stale
            w.c.post_bill(bill["id"], actor="accountant")
        self.assertEqual((c.approvals.get(bap["id"])["status"], c.bills.get(bill["id"])["status"]), ("invalidated", "approved"))
        revised = w.ap.revise_invoice(inv["id"], "ap clerk", reason="supplier reissued the invoice", evidence_hash=rev2["content_hash"])
        self.assertEqual((revised["version"], revised["status"]), (2, "received"))
        with self.assertRaises(BillIneligible):  # the bill's attached invoice is not the current one
            c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        state = c.bills.supplier_invoice_state(bill["id"])
        self.assertTrue(any("revised to version 2" in p for p in state["problems"]), state["problems"])
        self.assertTrue(any("newer revision" in p for p in state["problems"]), state["problems"])
        # re-match the reissued invoice to the same bill, then approve and post
        out = w.match_and_execute(inv["id"])
        self.assertEqual(out.result["bill"], bill["id"])
        relinked = c.bills.get(bill["id"])
        self.assertEqual((relinked["supplier_invoice_hash"], relinked["supplier_invoice_evidence_hash"]), (revised["content_hash"], rev2["content_hash"]))
        w.post(bill["id"])
        self.assertEqual(c.bills.get(bill["id"])["status"], "posted")
        attached = [e for e in c.audit.entries(entity_type="bill", entity_id=bill["id"]) if e["action"] == "bill.supplier_invoice_attached"]
        self.assertEqual(len(attached), 2)
        w.assert_books(self)

    def test_a_rejected_attached_invoice_stops_posting_until_another_is_matched(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-8101", "27000.00")
        w.match_and_execute(inv["id"])
        w.ap.revise_invoice(inv["id"], "ap clerk", reason="supplier withdrew it", amount="27000.01")
        w.ap.reject_invoice(inv["id"], "supplier withdrew the invoice", "ap clerk")
        with self.assertRaises(BillIneligible):
            c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        replacement = w.receive("SP-8102", "27000.00")
        w.match_and_execute(replacement["id"])
        self.assertEqual(c.bills.get(bill["id"])["supplier_invoice_id"], replacement["id"])
        w.post(bill["id"])
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 6. due dates, aging fields and close checks                                  #
# --------------------------------------------------------------------------- #

class DueDateAndCloseCheckTests(unittest.TestCase):
    def test_ap_items_carry_due_dates_and_invoice_numbers(self):
        w = World()
        c = w.c
        plain = w.certify({1: "10000"})  # no supplier invoice: created date + 30 days
        w.post(plain["id"])
        second = w.certify({1: "30000"})
        inv = w.receive("SP-4001", "18000.00", invoice_date="2026-10-05", due_date="2026-10-20")
        w.match_and_execute(inv["id"])
        w.post(second["id"])
        items = {i["bill_id"]: i for i in c.bills.ap_open_items(w.pid)["items"]}
        created = c.bills.get(plain["id"])["created_at"][:10]
        expected = (_dt.date.fromisoformat(created) + _dt.timedelta(days=30)).isoformat()
        self.assertEqual((items[plain["id"]]["due_date"], items[plain["id"]]["due_date_basis"], items[plain["id"]]["supplier_invoice_number"]),
                         (expected, "bill_created_plus_30_days", None))
        self.assertEqual((items[second["id"]]["due_date"], items[second["id"]]["supplier_invoice_number"], items[second["id"]]["open"]),
                         ("2026-10-20", "SP-4001", "18000.00"))
        w.assert_books(self)

    def test_unmatched_invoice_past_due_fails_the_close_check(self):
        w = World()
        c = w.c

        def check():
            return next(k for k in w.ap.close_checks("P1") if k["check"] == "ap_intake unmatched supplier invoices past due")

        self.assertTrue(check()["ok"])
        late = w.receive("SP-0901", "27000.00", invoice_date="2026-09-01")  # due 2026-10-01, before the period end
        w.receive("SP-1020", "500.00", invoice_date="2026-10-20")  # due 2026-11-19, after the period end
        self.assertFalse(check()["ok"])
        self.assertIn("SP-0901", check()["detail"])
        self.assertNotIn("SP-1020", check()["detail"])
        close = c.plugin("close")
        failing = [k for k in close.checklist("P1") if not k["ok"]]
        self.assertIn("ap_intake unmatched supplier invoices past due", [k["check"] for k in failing])
        self.assertTrue(any(i["kind"] == "close_check" and "SP-0901" in i["text"] for i in c.ricky.brief(w.pid)["items"]))
        # matching it clears the check
        w.certify({1: "30000"})
        w.match_and_execute(late["id"])
        self.assertTrue(check()["ok"])
        # a rejected invoice is not an open item either
        other = w.receive("SP-0902", "123.00", invoice_date="2026-09-02")
        self.assertFalse(check()["ok"])
        w.ap.reject_invoice(other["id"], "duplicate of a paper invoice already paid elsewhere", "ap clerk")
        self.assertTrue(check()["ok"])
        self.assertTrue(all(k["ok"] for k in w.ap.close_checks("P1")))


# --------------------------------------------------------------------------- #
# 7. corrected bills reopen their invoice for the replacement                  #
# --------------------------------------------------------------------------- #

class CorrectedBillRematchTests(unittest.TestCase):
    def test_invoice_of_a_corrected_bill_is_matched_to_the_replacement(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-3301", "27000.00")
        w.match_and_execute(inv["id"])
        w.post(bill["id"])
        c.bills.prepare_correction(bill["id"], "installed quantity was certified against the wrong SOV line", "accountant")
        ap = c.request_approval("bill.correct", bill["id"], actor_role="accountant")
        c.approve(ap["id"], approver="controller", approver_role="controller")
        w.execute(ap["id"], period_id="P1")
        self.assertTrue(w.ap.invoice(inv["id"])["orphaned_match"])
        replacement = w.certify({2: "30000"})
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual((res["status"], res["bill"]["id"]), ("matched", replacement["id"]))
        reopened = w.ap.invoice(inv["id"])
        self.assertEqual((reopened["version"], reopened["status"]), (2, "received"))
        w.execute(w.request_match(inv["id"])["id"])
        self.assertEqual(c.bills.get(replacement["id"])["supplier_invoice_id"], inv["id"])
        w.post(replacement["id"])
        self.assertEqual(c.bills.ap_open_items(w.pid)["subledger_total"], "27000.00")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 8. the bill's link copies the matched record                                 #
# --------------------------------------------------------------------------- #

def item_for(c, project_id, bill_id):
    return next(i for i in c.bills.ap_open_items(project_id)["items"] if i["bill_id"] == bill_id)


class AttachFromRecordTests(unittest.TestCase):
    def test_a_direct_reattach_cannot_rewrite_the_invoice_number_or_due_date(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-500", "27000.00", invoice_date="2026-09-01", due_date="2026-10-01")
        w.match_and_execute(inv["id"])
        approval_id = c.bills.get(bill["id"])["supplier_invoice_approval_id"]
        forged = {"id": inv["id"], "invoice_number": "SP-500-LATER", "invoice_date": inv["invoice_date"], "due_date": "2099-12-31",
                  "content_hash": inv["content_hash"], "evidence_hash": inv["evidence_hash"], "supplier_id": w.supplier["id"], "project_id": w.pid,
                  "amount": "27000.00", "match_approval_id": approval_id}
        with self.assertRaises(BillError) as cm:  # facts that differ from the invoice record
            c.bills.attach_supplier_invoice(bill["id"], forged, "someone")
        self.assertIn("differ from its record", str(cm.exception))
        with self.assertRaises(BillError) as cm:  # the record's own facts: that approval already attached it, to this very bill
            c.bills.attach_supplier_invoice(bill["id"], {"id": inv["id"], "match_approval_id": approval_id}, "someone")
        self.assertIn("takes effect once", str(cm.exception))
        # raw SQL with the audit entry the attachment guard looks for still has to copy the record, under a fresh approval
        c.audit.record("someone", "bill.supplier_invoice_attached", "bill", bill["id"], {
            "supplier_invoice_id": inv["id"], "supplier_invoice_number": "SP-500-LATER", "invoice_date": inv["invoice_date"], "due_date": "2099-12-31",
            "supplier_invoice_hash": inv["content_hash"], "supplier_invoice_evidence_hash": inv["evidence_hash"], "approval_id": approval_id})
        for sql in ("UPDATE bills SET due_date='2099-12-31', supplier_invoice_number='SP-500-LATER' WHERE id=?",
                    "UPDATE bills SET due_date='2099-12-31' WHERE id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (bill["id"],))
        linked = c.bills.get(bill["id"])
        self.assertEqual((linked["supplier_invoice_number"], linked["due_date"]), ("SP-500", "2026-10-01"))
        self.assertEqual(c.bills.supplier_invoice_state(bill["id"])["problems"], [])
        # the link is compared with the record field by field (number and due date too, not only the hashes)
        drifted = c.bills.supplier_invoice_state(dict(linked, supplier_invoice_number="SP-500-LATER", due_date="2099-12-31"))
        self.assertTrue(any("another number, due date" in p for p in drifted["problems"]), drifted["problems"])
        # bill.approve binds the recorded number and due date, and AP aging carries them
        bap = c.request_approval("bill.approve", bill["id"], actor_role="accountant")
        si = bap["manifest"]["bindings"]["supplier_invoice"]
        self.assertEqual((si["number"], si["due_date"], si["current"]["due_date"]), ("SP-500", "2026-10-01", "2026-10-01"))
        c.approve(bap["id"], approver="controller", approver_role="controller")
        w.c.post_bill(bill["id"], actor="accountant")
        item = item_for(c, w.pid, bill["id"])
        self.assertEqual((item["due_date"], item["due_date_basis"], item["supplier_invoice_number"], item["supplier_invoice_current"]),
                         ("2026-10-01", "supplier_invoice", "SP-500", True))
        self.assertEqual(w.ap.invoice(inv["id"])["due_date"], "2026-10-01")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 9. one supplier invoice, one live bill                                       #
# --------------------------------------------------------------------------- #

class OneInvoiceOneBillTests(unittest.TestCase):
    def test_a_revised_invoice_stays_on_its_bill_and_that_bill_takes_its_own_invoice(self):
        w = World()
        c = w.c
        bill1 = w.certify({1: "30000"})  # 27,000 due
        sp100 = w.receive("SP-100", "27000.00", invoice_date="2026-09-01")
        w.match_and_execute(sp100["id"])
        w.post(bill1["id"])
        bill2 = w.certify({1: "40000"})
        self.assertEqual(bill2["amount_due"], "9000.00")
        w.ap.revise_invoice(sp100["id"], "ap clerk", reason="supplier reissued SP-100 for the later work", amount="9000.00")
        # the revised invoice is still attached to bill 1: it is not matched to bill 2 as well
        res = w.ap.match(sp100["id"], "ap clerk")
        self.assertEqual((res["status"], res["exceptions"], res["bill"]), ("exception", ["amount_mismatch"], None))
        self.assertIn("attached to bill 1", res["details"][0]["detail"])
        with self.assertRaises(InvoiceIneligible):
            c.request_approval("ap_intake.match_invoice", sp100["id"], actor_role="accountant")
        self.assertEqual(w.ap.invoice(sp100["id"])["attached_bill_id"], bill1["id"])
        # bill 1's link no longer holds (its invoice was revised), so bill 1 takes its own invoice
        self.assertFalse(item_for(c, w.pid, bill1["id"])["supplier_invoice_current"])
        sp101 = w.receive("SP-101", "27000.00", invoice_date="2026-09-20")
        res = w.ap.match(sp101["id"], "ap clerk")
        self.assertEqual((res["status"], res["bill"]["id"]), ("matched", bill1["id"]))
        w.execute(w.request_match(sp101["id"])["id"])
        self.assertEqual(c.bills.get(bill1["id"])["supplier_invoice_id"], sp101["id"])
        # now SP-100 is free, and bill 2 takes it
        res = w.ap.match(sp100["id"], "ap clerk")
        self.assertEqual((res["status"], res["bill"]["id"]), ("matched", bill2["id"]))
        w.execute(w.request_match(sp100["id"])["id"])
        w.post(bill2["id"])
        items = {i["bill_id"]: i for i in c.bills.ap_open_items(w.pid)["items"]}
        self.assertEqual({b: (i["supplier_invoice_number"], i["open"], i["supplier_invoice_current"]) for b, i in items.items()},
                         {bill1["id"]: ("SP-101", "27000.00", True), bill2["id"]: ("SP-100", "9000.00", True)})
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM bills WHERE supplier_invoice_id=?", (sp100["id"],)), 1)
        # raw SQL never puts one invoice on two live bills
        b1 = c.bills.get(bill1["id"])
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("UPDATE bills SET supplier_invoice_id=?, supplier_invoice_hash=? WHERE id=?",
                         (sp100["id"], w.ap.invoice(sp100["id"])["content_hash"], b1["id"]))
        self.assertEqual(c.bills.get(bill1["id"])["supplier_invoice_id"], sp101["id"])
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 10. invoice records change only through the audited intake                    #
# --------------------------------------------------------------------------- #

class InvoiceRecordIntegrityTests(unittest.TestCase):
    def test_raw_sql_cannot_rewrite_an_invoice_its_review_or_its_match(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        small = w.receive("SP-610", "100.00", invoice_date="2026-09-01")
        a = w.receive("SP-611", "27000.00", invoice_date="2026-10-10")
        b = w.receive("SP-612", "27000.00", invoice_date="2026-10-12")  # a near duplicate of SP-611
        self.assertTrue(b["duplicate_blocking"])
        res = w.ap.match(small["id"], "ap clerk")
        now = "2026-10-12T00:00:00Z"
        probes = [
            ("raise the amount under a forged hash", "UPDATE ap_invoices SET amount='27000.00', version=version+1, content_hash='forged2' WHERE id=?", small),
            ("clear the duplicate flag under a forged hash",
             "UPDATE ap_invoices SET possible_duplicate=0, duplicate_of_json='[]', version=version+1, content_hash='forged1' WHERE id=?", b),
            ("record a duplicate review nobody made",
             f"UPDATE ap_invoices SET duplicate_cleared_by='someone', duplicate_cleared_at='{now}', duplicate_clear_reason='looks fine' WHERE id=?", b),
            ("mark the match state", "UPDATE ap_invoices SET match_status='matched', match_basis='progress' WHERE id=?", small),
            ("point at another computation", "UPDATE ap_invoices SET match_attempt_id='apm_forged' WHERE id=?", small),
            ("reject without the intake", f"UPDATE ap_invoices SET status='rejected', rejected_by='x', rejected_at='{now}', reject_reason='x' WHERE id=?", small),
        ]
        for label, sql, inv in probes:
            with self.subTest(probe=label), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (inv["id"],))
        with self.assertRaises(sqlite3.DatabaseError):  # a computation nobody ran
            c.db.execute("INSERT INTO ap_invoice_matches (id, invoice_id, invoice_version, basis, status, exceptions_json, result_json, result_hash, "
                         "computed_by, computed_at) VALUES ('apm_forged', ?, 1, 'progress', 'matched', '[]', '{}', 'x', 'someone', ?)", (small["id"], now))
        self.assertEqual((w.ap.invoice(small["id"])["amount"], w.ap.invoice(small["id"])["match_attempt_id"]), ("100.00", res["attempt_id"]))
        self.assertTrue(w.ap.invoice(b["id"])["duplicate_blocking"])
        self.assertEqual(w.ap.match(b["id"], "ap clerk")["exceptions"], ["possible_duplicate"])
        # a revised invoice is never re-matched by its earlier approval
        w.match_and_execute(a["id"])
        w.ap.revise_invoice(a["id"], "ap clerk", reason="supplier corrected the due date", due_date="2026-11-30")
        self.assertEqual(w.ap.match(a["id"], "ap clerk")["status"], "matched")
        with self.assertRaises(sqlite3.DatabaseError):
            c.db.execute("UPDATE ap_invoices SET status='matched', matched_at=? WHERE id=?", (now, a["id"]))
        self.assertEqual(w.ap.invoice(a["id"])["status"], "received")
        self.assertEqual(c.bills.get(bill["id"])["supplier_invoice_id"], a["id"])
        intact = next(k for k in w.ap.close_checks("P1") if k["check"] == "ap_intake supplier invoice records intact")
        self.assertTrue(intact["ok"], intact)
        w.assert_books(self)

    def test_a_forged_revision_is_caught_by_its_content_hash_even_with_a_forged_audit_entry(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-620", "100.00", invoice_date="2026-09-01")
        # whoever writes the audit entry the guard looks for still cannot make the record hash
        c.audit.record("someone", "ap_intake.invoice_revised", "ap_invoice", inv["id"],
                       {"version": 2, "content_hash": "forged", "amount": "27000.00", "possible_duplicate": 0})
        c.db.execute("UPDATE ap_invoices SET amount='27000.00', version=2, content_hash='forged' WHERE id=?", (inv["id"],))
        tampered = w.ap.invoice(inv["id"])
        self.assertIn("does not hash to its recorded content hash", tampered["integrity_problem"])
        with self.assertRaises(APIntakeError):
            w.ap.match(inv["id"], "ap clerk")
        with self.assertRaises(InvoiceIneligible):
            c.request_approval("ap_intake.match_invoice", inv["id"], actor_role="accountant")
        with self.assertRaises(APIntakeError):  # a revision would re-hash (launder) the forged facts
            w.ap.revise_invoice(inv["id"], "ap clerk", reason="tidy up", due_date="2026-12-31")
        intact = next(k for k in w.ap.close_checks("P1") if k["check"] == "ap_intake supplier invoice records intact")
        self.assertFalse(intact["ok"])
        self.assertIn("SP-620", intact["detail"])
        self.assertEqual(c.project_state(w.pid)[PLUGIN_NAME]["summary"]["integrity_failures"], 1)
        self.assertIsNone(c.bills.get(bill["id"])["supplier_invoice_id"])
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM ap_invoice_matches WHERE invoice_id=?", (inv["id"],)), 0)


# --------------------------------------------------------------------------- #
# 11. an invoice whose bill was voided or corrected is unmatched               #
# --------------------------------------------------------------------------- #

class OrphanedMatchTests(unittest.TestCase):
    @staticmethod
    def check(w):
        return next(k for k in w.ap.close_checks("P1") if k["check"] == "ap_intake unmatched supplier invoices past due")

    def test_an_invoice_whose_bill_was_voided_fails_the_past_due_check_until_rematched(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-200", "27000.00", invoice_date="2026-09-01")  # due 2026-10-01, before P1 ends
        w.match_and_execute(inv["id"])
        self.assertTrue(self.check(w)["ok"])
        c.bills.void(bill["id"], actor="pm", reason="re-measured")
        orphan = w.ap.invoice(inv["id"])
        self.assertEqual((orphan["status"], orphan["orphaned_match"], orphan["unmatched"], orphan["overdue"]),
                         ("matched", True, True, "2026-10-01" < today()))
        check = self.check(w)
        self.assertFalse(check["ok"])
        self.assertIn("SP-200", check["detail"])
        self.assertIn("voided", check["detail"])
        summary = c.project_state(w.pid)[PLUGIN_NAME]["summary"]
        self.assertEqual((summary["matched"], summary["orphaned_matches"], summary["unmatched"], summary["open_amount"]), (0, 1, 1, "27000.00"))
        # the re-certified bill takes it: matched again, the check passes
        fresh = w.certify({1: "30000"})
        out = w.match_and_execute(inv["id"])
        self.assertEqual((out.result["bill"], w.ap.invoice(inv["id"])["version"]), (fresh["id"], 2))
        self.assertTrue(self.check(w)["ok"])
        self.assertEqual(c.project_state(w.pid)[PLUGIN_NAME]["summary"]["matched"], 1)
        w.assert_books(self)

    def test_an_invoice_whose_bill_was_corrected_fails_the_past_due_check_until_rematched(self):
        w = World()
        c = w.c
        bill = w.certify({1: "30000"})
        inv = w.receive("SP-201", "27000.00", invoice_date="2026-09-01")
        w.match_and_execute(inv["id"])
        w.post(bill["id"])
        c.bills.prepare_correction(bill["id"], "certified on the wrong SOV line (synthetic)", "accountant")
        ap = c.request_approval("bill.correct", bill["id"], actor_role="accountant")
        c.approve(ap["id"], approver="controller", approver_role="controller")
        w.execute(ap["id"], period_id="P1")
        check = self.check(w)
        self.assertFalse(check["ok"])
        self.assertIn("corrected", check["detail"])
        self.assertEqual(c.project_state(w.pid)[PLUGIN_NAME]["summary"]["orphaned_matches"], 1)
        replacement = w.certify({2: "30000"})
        self.assertEqual(w.match_and_execute(inv["id"]).result["bill"], replacement["id"])
        self.assertTrue(self.check(w)["ok"])
        w.post(replacement["id"])
        self.assertEqual(c.bills.ap_open_items(w.pid)["subledger_total"], "27000.00")
        w.assert_books(self)


# --------------------------------------------------------------------------- #
# 12. a PO invoice matched before its PO bill exists is linked later           #
# --------------------------------------------------------------------------- #

class PurchaseOrderBillLaterTests(unittest.TestCase):
    def test_a_po_invoice_matched_before_its_bill_is_linked_once_the_bill_is_certified(self):
        w = PurchaseOrderWorld()
        c = w.c
        w.receive_equipment(w.e1)
        inv = w.po_invoice("PO-L-1", (w.e1, "29000.00"), invoice_date="2026-09-01")  # due 2026-10-01
        self.assertIsNone(w.match_and_execute(inv["id"]).result["bill"])
        with self.assertRaises(APIntakeError):  # no PO bill yet: it stays matched to its receipts
            w.ap.match(inv["id"], "ap clerk")
        po_bill = c.bills.certify(commitment_id=w.po, period_id="P1",
                                  installed=[{"sov_line_id": c.commitments.get(w.po)["sov"][0]["id"], "cumulative_installed": "29000"}], actor="pm")
        res = w.ap.match(inv["id"], "ap clerk")
        self.assertEqual((res["status"], res["basis"], res["bill"]["id"]), ("matched", "purchase_order", po_bill["id"]))
        reopened = w.ap.invoice(inv["id"])
        self.assertEqual((reopened["version"], reopened["status"]), (2, "received"))
        self.assertIn("po_bill_certified", [loads_payload(e).get("reason") for e in c.audit.entries(entity_type="ap_invoice", entity_id=inv["id"])
                                             if e["action"] == "ap_intake.match_reopened"])
        w.execute(w.request_match(inv["id"])["id"])
        linked = c.bills.get(po_bill["id"])
        self.assertEqual((linked["supplier_invoice_number"], linked["due_date"]), ("PO-L-1", "2026-10-01"))
        w.post(po_bill["id"])
        item = item_for(c, w.pid, po_bill["id"])
        self.assertEqual((item["due_date"], item["due_date_basis"], item["supplier_invoice_number"]), ("2026-10-01", "supplier_invoice", "PO-L-1"))
        # the pump is still invoiced once
        again = w.po_invoice("PO-L-2", (w.e1, "29000.00"), invoice_date="2026-09-25")
        self.assertEqual(w.ap.match(again["id"], "ap clerk")["exceptions"], ["over_commitment"])
        w.assert_books(self)


def loads_payload(entry):
    return json.loads(entry["payload_json"])


if __name__ == "__main__":
    unittest.main()
