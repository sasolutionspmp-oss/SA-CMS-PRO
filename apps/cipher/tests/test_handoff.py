"""Shadow-finance hand-off with receipts: package content and exact CSV, acknowledgement
through an approval, stale acknowledgements, omissions, close checks, immutability and
adversarial input (forged raw rows, stale approvals forced through the core API, Unicode receipt
references).  Every scenario builds its own synthetic workspace."""
import csv
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from apps.cipher.tests.bill_helpers import approve_and_post_bill
from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.core.audit import GENESIS
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.core.ids import canonical_json, sha256_hex
from apps.cipher.domain.handoff import (
    ACK_GUARDS_SCHEMA_NAME, AP_COLUMNS, AR_COLUMNS, CHECK_NAME, FORMAT, GUARDS_SCHEMA_NAME, JOURNAL_COLUMNS, LABEL, LABEL_LINES, OP_ACKNOWLEDGE,
    PLUGIN_NAME, PREPARED_ACTION, SCHEMA_NAME, HandoffDuplicate, HandoffError, HandoffRefused, HandoffStale, _cell, _csv_files, label_line, read_csv,
    ref_key,
)
from apps.cipher.service import Cipher, CoreReconciliationChecks, RoleNotAuthorized

ENTITY = "S&A Solutions LLC (synthetic)"
CSV_HEAD = f"# {LABEL} | period P1 | {FORMAT}"
JOURNAL_HEADER = ("period_id,journal_id,posted_at,description,source_type,source_id,source_version,rule_version,approval_id,"
                  "reversal_of,reversed_by,posted_by,line_no,account_code,account_name,debit,credit,project_id,party_id,memo")
RAW_TIME = "2026-10-12T00:00:00Z"
NO_AUDIT_ENTRY = f"it has no {PREPARED_ACTION} audit entry (it was not prepared through prepare_handoff)"
AUDIT_MISMATCH = (f"its {PREPARED_ACTION} audit entry does not record this package "
                  "(period, sequence, hash, journal count, totals, predecessor, label and preparer)")
AUDIT_BROKEN = f"its {PREPARED_ACTION} audit entry is not intact in the hash-chained audit log"
RAW_DETAILS = """INSERT INTO handoff_receipt_details (id, handoff_id, version, receipt_ref, accountant, recorded_by, recorded_at)
                 VALUES (?,?,?,?,?,'raw',?)"""


def lines_of(text):
    """Split an RFC 4180 rendering into its CRLF-terminated lines (the last line is terminated too)."""
    assert text.endswith("\r\n"), repr(text[-10:])
    return text[:-2].split("\r\n")


def csv_line(values):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerow(values)
    return buf.getvalue()[:-2]


def open_item_lines(items, columns, exact):
    """Expected CSV lines for one open item: every documented column is a literal from ``exact``;
    only a column a sibling subledger appends after them (sorted) takes the item's own value, rendered
    the way the module renders any cell (``_cell``: booleans as true/false, None empty, JSON for lists)."""
    assert len(items) == 1, items
    assert set(exact) == set(columns), sorted(set(columns) ^ set(exact))
    for c in columns:
        assert not any(ch in exact[c] for ch in ',"\r\n'), exact[c]  # documented literals are plain: no quoting expected
    item = items[0]
    extra = sorted(set(item) - set(columns))
    row = [exact[c] for c in columns] + [_cell(item.get(c)) for c in extra]
    return [CSV_HEAD, csv_line(list(columns) + extra), csv_line(row)]


def chained_audit_entry(s, row, *, payload=None, broken=False):
    """Append a ``handoff.prepared`` audit entry for a raw row the way a writer able to compute SHA-256
    would (correct payload hash, entry hash and link to the previous entry), or with a wrong entry hash."""
    if payload is None:
        payload = {"period_id": row["period_id"], "sequence": row["sequence"], "package_hash": row["package_hash"], "journal_count": row["journal_count"],
                   "total_debit": row["total_debit"], "total_credit": row["total_credit"], "supersedes": row["supersedes"], "approvals_invalidated": 0,
                   "label": LABEL}
    payload_json = canonical_json(payload)
    payload_hash = sha256_hex(payload_json)
    prev = s.c.db.scalar("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1") or GENESIS
    entry_hash = sha256_hex("|".join([prev, RAW_TIME, row["prepared_by"], PREPARED_ACTION, "handoff", row["id"], payload_hash]))
    if broken:
        entry_hash = sha256_hex("broken:" + entry_hash)
    s.c.db.execute("""INSERT INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash)
                      VALUES (?,?,?,?,?,?,?,?,?)""", (RAW_TIME, row["prepared_by"], PREPARED_ACTION, "handoff", row["id"], payload_json, payload_hash, prev, entry_hash))


def forge(s, base, *, audit="chained", **over):
    """A raw package row on top of ``base`` (next sequence, superseding it); by default it copies the
    base's stored JSON with its correct SHA-256 and the base's header, and ``over`` changes any column.
    ``audit``: "chained" also appends a correctly chained ``handoff.prepared`` audit entry for it (the
    strongest raw writer), "mismatched" one that records a different package hash, "broken" one with a
    wrong entry hash, None none at all."""
    text = over.pop("package_json", None)
    if text is None:
        text = s.c.db.scalar("SELECT package_json FROM handoff_packages WHERE id=?", (base["id"],))
    row = {"id": f"hof_raw_{base['sequence'] + 1}", "period_id": base["period_id"], "sequence": base["sequence"] + 1, "label": LABEL, "format": FORMAT,
           "package_json": text, "package_hash": sha256_hex(text), "journal_count": base["journal_count"], "total_debit": base["total_debit"],
           "total_credit": base["total_credit"], "supersedes": base["id"], "prepared_by": "raw", "prepared_at": RAW_TIME}
    row.update(over)
    s.c.db.execute("""INSERT INTO handoff_packages (id, period_id, sequence, label, format, package_json, package_hash, journal_count, total_debit,
                      total_credit, supersedes, prepared_by, prepared_at) VALUES (:id, :period_id, :sequence, :label, :format, :package_json, :package_hash,
                      :journal_count, :total_debit, :total_credit, :supersedes, :prepared_by, :prepared_at)""", row)
    if audit == "chained":
        chained_audit_entry(s, row)
    elif audit == "mismatched":
        chained_audit_entry(s, {**row, "package_hash": sha256_hex("another package:" + row["package_hash"])})
    elif audit == "broken":
        chained_audit_entry(s, row, broken=True)
    else:
        assert audit is None, audit
    return row


def raw_receipt(s, h, d, approval_id, *, omission_count, acknowledged_by="accountant-1"):
    s.c.db.execute("""INSERT INTO handoff_receipts (id, handoff_id, receipt_details_id, receipt_ref, accountant, package_hash, journal_count, total_debit,
                      total_credit, omission_count, approval_id, acknowledged_by, acknowledged_at) VALUES ('hrc_raw',?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (h["id"], d["id"], d["receipt_ref"], d["accountant"], h["package_hash"], h["journal_count"], h["total_debit"], h["total_credit"],
                    omission_count, approval_id, acknowledged_by, RAW_TIME))


class Scenario:
    """Fresh workspace: verified supplier, customer, one project, open periods P1 (Oct) and P2 (Nov),
    and optionally P0 (Sep) for subledger activity outside the handed-off period."""

    def __init__(self, path=":memory:", *, keep=None, with_p0=False):
        self.c = Cipher(path)
        if keep is not None:
            for name in list(self.c._plugins):
                if name not in keep:
                    del self.c._plugins[name]
        self.h = self.c.plugin(PLUGIN_NAME)
        self.supplier = self.c.add_party(kind="supplier", name="Synthetic Subcontractor H", destination="ACH-SIM-H001")
        self.c.verify_destination(self.supplier["id"], destination="ACH-SIM-H001", verified_by="owner")
        self.customer = self.c.add_party(kind="customer", name="Synthetic Owner Agency H")
        self.project = self.c.create_project(name="Synthetic hand-off project", entity=ENTITY, budget="100000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        if with_p0:
            self.c.open_period("P0", "September 2026", "2026-09-01", "2026-09-30")
        self.c.open_period("P1", "October 2026", "2026-10-01", "2026-10-31")
        self.c.open_period("P2", "November 2026", "2026-11-01", "2026-11-30")
        self._n = 0

    def journal(self, lines, *, period="P1", description="Synthetic journal", source_type="test_setup"):
        self._n += 1
        return self.c.ledger.post(period_id=period, description=description, lines=lines, source_type=source_type,
                                  source_id=f"SYN-{self._n}", source_version="1", posted_by="owner")

    def contribution(self, amount, *, period="P1"):
        return self.journal([{"account": "1000", "debit": amount, "memo": "owner funds"}, {"account": "3000", "credit": amount, "memo": "owner funds"}],
                            period=period, description="Synthetic owner contribution", source_type="owner_contribution")

    def expense(self, amount, *, period="P1", memo="paid from bank"):
        return self.journal([{"account": "5100", "debit": amount, "project_id": self.pid, "memo": memo},
                             {"account": "1000", "credit": amount, "project_id": self.pid, "memo": "paid from bank"}],
                            period=period, description='Synthetic expense, pump "A"', source_type="expense_paid")

    def subledgers(self, period="P0"):
        """One posted supplier bill (18,000.00 due) and one posted prime bill (27,000.00 due) in ``period``;
        returns (commitment, bill, prime bill)."""
        cmt = self.c.commitments.create(project_id=self.pid, supplier_id=self.supplier["id"], title="Synthetic subcontract XX 10 00",
                                        sov_lines=[{"description": "Placeholder scope XX 10 00", "amount": "60000"}], retainage_rate="0.10", actor="owner")
        self.c.approve_and_execute("commitment.execute", cmt["id"])
        cmt = self.c.commitments.get(cmt["id"])
        bill = self.c.bills.certify(commitment_id=cmt["id"], period_id=period, installed=[{"sov_line_id": cmt["sov"][0]["id"], "cumulative_installed": "20000"}], actor="owner")
        approve_and_post_bill(self.c, bill["id"], approver="owner", approver_role="owner", poster="accountant")
        prime = self.c.receivables.certify(project_id=self.pid, period_id=period, certified_cumulative="30000", retainage_rate="0.10", actor="owner")
        self.c.approve_and_execute("prime_bill.approve", prime["id"])
        return cmt, self.c.bills.get(bill["id"]), self.c.receivables.get(prime["id"])

    def request(self, handoff_id, *, role="accountant"):
        return self.c.request_approval(OP_ACKNOWLEDGE, handoff_id, actor_role=role, requested_by="owner")

    def grant(self, handoff_id, *, role="accountant"):
        ap = self.request(handoff_id, role=role)
        self.c.approve(ap["id"], approver="accountant-1", approver_role=role)
        return ap

    def acknowledge(self, handoff_id, ref, accountant="Synthetic Accountant A"):
        self.h.record_receipt_details(handoff_id, ref, accountant, "owner")
        ap = self.grant(handoff_id)
        return self.c.execute(ap["id"], actor="accountant-1")

    def receipts(self):
        return self.c.db.scalar("SELECT COUNT(*) FROM handoff_receipts")

    def assert_books_sound(self, test):
        test.assertTrue(self.c.ledger.trial_balance()["balanced"])
        test.assertTrue(self.c.audit.verify_chain()["ok"])


class PackageTests(unittest.TestCase):
    def test_package_content_and_exact_csv(self):
        s = Scenario(with_p0=True)
        cmt, bill, prime = s.subledgers("P0")
        j1 = s.contribution("10000")
        j2 = s.expense("1234.56", memo="=SUM(A1:A2)")
        h = s.h.prepare_handoff("P1", "owner")

        self.assertEqual((h["status"], h["label"], h["format"], h["sequence"], h["period_id"]), ("prepared", LABEL, FORMAT, 1, "P1"))
        self.assertEqual((h["journal_count"], h["total_debit"], h["total_credit"]), (2, "11234.56", "11234.56"))
        self.assertTrue(h["id"].startswith("hof_"))
        self.assertIsNone(h["supersedes"])
        self.assertIsNone(h["receipt"])
        self.assertTrue(h["is_latest"] and h["hash_verified"])
        self.assertEqual((h["integrity_ok"], h["integrity_problems"]), (True, []))
        pkg = h["package"]
        self.assertEqual(h["package_hash"], sha256_hex(canonical_json(pkg)))
        self.assertEqual(pkg, s.h.package(h["id"]))
        self.assertEqual((pkg["label"], pkg["format"], pkg["currency"], pkg["entities"]), (LABEL, FORMAT, "USD", [ENTITY]))
        self.assertEqual(pkg["period"], {"id": "P1", "name": "October 2026", "start_date": "2026-10-01", "end_date": "2026-10-31"})
        self.assertEqual((pkg["journal_count"], pkg["totals"]), (2, {"debit": "11234.56", "credit": "11234.56"}))

        # journals: only P1's, in posting order, with lines and exact money
        self.assertEqual([j["id"] for j in pkg["journals"]], [j1["id"], j2["id"]])
        first, second = pkg["journals"]
        self.assertEqual((first["total_debit"], first["total_credit"], first["reversed_by"]), ("10000.00", "10000.00", None))
        self.assertEqual([(ln["account_code"], ln["account_name"], ln["debit"], ln["credit"]) for ln in second["lines"]],
                         [("5100", "Project cost - reimbursable expense", "1234.56", "0.00"), ("1000", "Operating bank", "0.00", "1234.56")])
        self.assertEqual(second["lines"][0]["memo"], "=SUM(A1:A2)")  # the JSON keeps the exact text

        # trial balance for the period only
        tb = pkg["trial_balance"]
        self.assertEqual((tb["period_id"], tb["total_debit"], tb["total_credit"], tb["balanced"], tb["journal_count"]), ("P1", "11234.56", "11234.56", True, 2))
        self.assertEqual({r["code"]: (r["debit"], r["credit"], r["balance"]) for r in tb["rows"]},
                         {"1000": ("10000.00", "1234.56", "8765.44"), "3000": ("0.00", "10000.00", "10000.00"), "5100": ("1234.56", "0.00", "1234.56")})

        # AP and AR open items are entity-wide, reconciled, with exact money
        self.assertEqual((pkg["ap"]["subledger_total"], pkg["ap"]["control_balance"], pkg["ap"]["reconciled"]), ("18000.00", "18000.00", True))
        self.assertEqual((pkg["ar"]["subledger_total"], pkg["ar"]["control_balance"], pkg["ar"]["reconciled"]), ("27000.00", "27000.00", True))
        self.assertEqual(pkg["reconciliations"]["ap"], {"subledger_total": "18000.00", "control_balance": "18000.00", "reconciled": True})
        self.assertEqual(pkg["reconciliations"]["ar"], {"subledger_total": "27000.00", "control_balance": "27000.00", "reconciled": True})
        self.assertIn("not reconstructed", pkg["open_items_basis"])
        # every core subledger reconciliation the service exposes, exactly as the service reported it at preparation
        core = {label: getattr(getattr(s.c, domain), method)() for label, domain, method in CoreReconciliationChecks.CHECKS
                if getattr(getattr(s.c, domain), method, None) is not None}
        expected_core = {
            "retainage payable reconciled (2050)": ("2000.00", "2000.00", True),  # 10% of the 20,000.00 certified
            "stored materials reconciled (1300)": ("0.00", "0.00", True),
            "retainage receivable reconciled (1150)": ("3000.00", "3000.00", True),  # 10% of the 30,000.00 prime bill
            "provider clearing reconciled (1200)": ("0.00", "0.00", True),
            "customer deposits reconciled (2400)": ("0.00", "0.00", True),  # no customer advance in this fixture
        }
        self.assertEqual(set(core), set(expected_core))
        self.assertEqual(set(pkg["reconciliations"]), {"ap", "ar"} | set(expected_core))
        for label, live in core.items():
            self.assertEqual(pkg["reconciliations"][label], json.loads(canonical_json(live)), label)
            got = pkg["reconciliations"][label]
            self.assertEqual((got["subledger_total"], got["control_balance"], got["reconciled"]), expected_core[label], label)

        # exact CSV lines
        t1, t2 = first["posted_at"], second["posted_at"]
        pid = s.pid
        self.assertEqual(lines_of(pkg["csv"]["journals.csv"]), [
            CSV_HEAD,
            JOURNAL_HEADER,
            f"P1,{j1['id']},{t1},Synthetic owner contribution,owner_contribution,SYN-1,1,cipher-posting-rules/1,,,,owner,1,1000,Operating bank,10000.00,0.00,,,owner funds",
            f"P1,{j1['id']},{t1},Synthetic owner contribution,owner_contribution,SYN-1,1,cipher-posting-rules/1,,,,owner,2,3000,Owner equity,0.00,10000.00,,,owner funds",
            f'P1,{j2["id"]},{t2},"Synthetic expense, pump ""A""",expense_paid,SYN-2,1,cipher-posting-rules/1,,,,owner,1,5100,Project cost - reimbursable expense,1234.56,0.00,{pid},,\'=SUM(A1:A2)',
            f'P1,{j2["id"]},{t2},"Synthetic expense, pump ""A""",expense_paid,SYN-2,1,cipher-posting-rules/1,,,,owner,2,1000,Operating bank,0.00,1234.56,{pid},,paid from bank',
        ])
        # AP / AR: every documented column is an independent literal (a field a sibling subledger
        # appends after them, sorted, is the only cell taken from the item itself)
        self.assertEqual((prime["status"], len(prime["created_at"]) >= 10), ("posted", True))
        self.assertEqual(lines_of(pkg["csv"]["ap.csv"]), open_item_lines(pkg["ap"]["items"], AP_COLUMNS, {
            "kind": "supplier_bill", "bill_id": bill["id"], "commitment_id": cmt["id"], "supplier_id": s.supplier["id"], "project_id": pid,
            "sequence": "1", "amount_due": "18000.00", "paid": "0.00", "open": "18000.00",
        }))
        self.assertEqual(lines_of(pkg["csv"]["ar.csv"]), open_item_lines(pkg["ar"]["items"], AR_COLUMNS, {
            "kind": "prime_bill", "source": "prime_bill", "prime_bill_id": prime["id"], "retainage_invoice_id": "", "invoice_id": "",
            "project_id": pid, "customer_id": s.customer["id"], "sequence": "1", "period_id": "P0", "date": prime["created_at"][:10],
            "status": "posted", "amount_due": "27000.00", "received": "0.00", "open": "27000.00",
        }))
        self.assertTrue(lines_of(pkg["csv"]["ap.csv"])[1].startswith("kind,bill_id,commitment_id,supplier_id,project_id,sequence,amount_due,paid,open"))
        self.assertTrue(lines_of(pkg["csv"]["ar.csv"])[1].startswith(
            "kind,source,prime_bill_id,retainage_invoice_id,invoice_id,project_id,customer_id,sequence,period_id,date,status,amount_due,received,open"))
        # supplier bills carry their commitment and project although ap_open_items() leaves them out
        label, header, ap_rows = read_csv(pkg["csv"]["ap.csv"])
        self.assertEqual((label, header[:len(AP_COLUMNS)]), (CSV_HEAD, list(AP_COLUMNS)))
        self.assertEqual([(r["bill_id"], r["commitment_id"], r["project_id"], r["open"]) for r in ap_rows], [(bill["id"], cmt["id"], pid, "18000.00")])
        _, _, ar_rows = read_csv(pkg["csv"]["ar.csv"])
        self.assertEqual([(r["prime_bill_id"], r["customer_id"], r["project_id"], r["open"]) for r in ar_rows], [(prime["id"], s.customer["id"], pid, "27000.00")])
        self.assertEqual(s.h.csv_file(h["id"], "ap.csv"), pkg["csv"]["ap.csv"])
        with self.assertRaises(HandoffError):
            s.h.csv_file(h["id"], "secrets.csv")

        entries = [e for e in s.c.audit.entries(entity_type="handoff", entity_id=h["id"]) if e["action"] == "handoff.prepared"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(json.loads(entries[0]["payload_json"])["package_hash"], h["package_hash"])
        v = s.h.verify(h["id"])
        self.assertEqual((v["ok"], v["canonical"], v["recomputed"], v["integrity_problems"]), (True, True, h["package_hash"], []))
        s.assert_books_sound(self)

    def test_csv_label_record_is_quoted_and_standard_readers_work_after_it(self):
        s = Scenario()
        odd = 'P,"9'
        s.c.open_period(odd, "Synthetic odd period", "2026-12-01", "2026-12-31")
        j = s.contribution("42.00", period=odd)
        h = s.h.prepare_handoff(odd, "owner")
        text = h["package"]["csv"]["journals.csv"]
        # the one-field label record goes through the CSV writer, so the comma and quote are quoted
        self.assertEqual(lines_of(text)[0], f'"# {LABEL} | period P,""9 | {FORMAT}"')
        label, header, rows = read_csv(text)
        self.assertEqual((label, header), (label_line(odd), list(JOURNAL_COLUMNS)))
        self.assertEqual([(r["period_id"], r["journal_id"], r["line_no"], r["account_code"], r["debit"], r["credit"]) for r in rows],
                         [(odd, j["id"], "1", "1000", "42.00", "0.00"), (odd, j["id"], "2", "3000", "0.00", "42.00")])
        # RFC 4180 from the second record on: a standard reader sees the real header once the label record is skipped
        body = text.split("\r\n", LABEL_LINES)[LABEL_LINES]
        self.assertEqual(list(csv.DictReader(io.StringIO(body, newline=""))), rows)
        for bad in ("kind,bill_id\r\nx,y\r\n", f"# {LABEL} | period P1 | {FORMAT}\r\na,b\r\n1\r\n", None):
            with self.assertRaises(HandoffError):
                read_csv(bad)

    def test_empty_period_package_and_duplicate_rejected(self):
        s = Scenario()
        h = s.h.prepare_handoff("P2", "owner")
        self.assertEqual((h["journal_count"], h["total_debit"], h["total_credit"]), (0, "0.00", "0.00"))
        self.assertEqual(lines_of(h["package"]["csv"]["journals.csv"]), [CSV_HEAD.replace("period P1", "period P2"), JOURNAL_HEADER])
        with self.assertRaises(HandoffDuplicate) as cm:
            s.h.prepare_handoff("P2", "owner")
        self.assertIn(h["id"], str(cm.exception))
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_packages"), 1)

        # a change in the period makes a new package that supersedes the first
        s.contribution("250.00", period="P2")
        h2 = s.h.prepare_handoff("P2", "owner")
        self.assertEqual((h2["sequence"], h2["supersedes"], h2["journal_count"], h2["total_debit"]), (2, h["id"], 1, "250.00"))
        old = s.h.handoff(h["id"])
        self.assertEqual((old["is_latest"], old["superseded_by"]), (False, h2["id"]))
        self.assertNotEqual(h2["package_hash"], h["package_hash"])

    def test_a_reconciliation_that_raises_is_recorded_in_the_package(self):
        s = Scenario()
        s.contribution("100.00")
        with mock.patch.object(s.c.payments, "clearing_items", side_effect=RuntimeError("synthetic provider outage"), create=True):
            h = s.h.prepare_handoff("P1", "owner")
        rec = h["package"]["reconciliations"]
        # the package says what it could not reconcile instead of hiding it, and preparation goes on
        self.assertEqual(rec["provider clearing reconciled (1200)"], {"error": "RuntimeError: synthetic provider outage"})
        self.assertEqual((h["status"], h["journal_count"], h["total_debit"], h["integrity_ok"]), ("prepared", 1, "100.00", True))
        self.assertEqual(rec["ap"], {"subledger_total": "0.00", "control_balance": "0.00", "reconciled": True})
        self.assertTrue(s.h.verify(h["id"])["ok"])
        # with the service healthy again nothing in P1 changed, but the reconciliation does: a new package
        h2 = s.h.prepare_handoff("P1", "owner")
        self.assertEqual(h2["package"]["reconciliations"]["provider clearing reconciled (1200)"]["reconciled"], True)
        self.assertEqual((h2["sequence"], h2["supersedes"]), (2, h["id"]))
        s.assert_books_sound(self)

    def test_invalid_input_refused(self):
        s = Scenario()
        s.contribution("100")
        for bad in ("", "   ", None, 7, "P9"):
            with self.assertRaises(HandoffError):
                s.h.prepare_handoff(bad, "owner")
        for bad_actor in ("", None, "a\nb"):
            with self.assertRaises(HandoffError):
                s.h.prepare_handoff("P1", bad_actor)
        h = s.h.prepare_handoff("P1", "owner")
        for ref, name in (("", "Synthetic Accountant A"), ("RCPT-1", "  "), (12, "Synthetic Accountant A"), ("R" * 201, "Synthetic Accountant A"), ("RCPT\r\n2", "A")):
            with self.assertRaises(HandoffError):
                s.h.record_receipt_details(h["id"], ref, name, "owner")
        with self.assertRaises(HandoffError):
            s.h.record_receipt_details("hof_unknown", "RCPT-1", "Synthetic Accountant A", "owner")
        with self.assertRaises(HandoffError):
            s.c.request_approval("handoff.bogus", h["id"], actor_role="owner")
        with self.assertRaises(HandoffError):
            s.c.request_approval(OP_ACKNOWLEDGE, "hof_unknown", actor_role="owner")
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_receipt_details"), 0)
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM approvals WHERE operation LIKE 'handoff.%'"), 0)

    def test_closed_period_refused(self):
        s = Scenario()
        s.contribution("100")
        s.c.close_period("P1")
        with self.assertRaises(HandoffError) as cm:
            s.h.prepare_handoff("P1", "owner")
        self.assertIn("closed", str(cm.exception))
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_packages"), 0)

    def test_unbalanced_books_are_never_handed_off(self):
        s = Scenario()
        j = s.contribution("100.00")
        # the core seals posted journals, so unbalanced books cannot be produced through the database ...
        with self.assertRaises(sqlite3.DatabaseError):
            s.c.db.execute("INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES ('jln_raw_tamper', ?, 3, '1000', '1.00', '0.00', 'raw')", (j["id"],))
        # ... so the refusals are driven by stubbing what the hand-off reads
        real_tb = s.c.ledger.trial_balance
        real_journals = s.h._period_journals

        def lopsided_tb(period_id=None):
            return {**real_tb(period_id), "total_credit": "99.00", "balanced": False}

        def miscounted_tb(period_id=None):
            tb = real_tb(period_id)
            return {**tb, "journal_count": tb["journal_count"] + 1}

        def lopsided_journal(period_id):
            journals = real_journals(period_id)
            journals[0]["total_credit"] = "99.00"
            return journals

        def empty_journal(period_id):
            journals = real_journals(period_id)
            journals[0]["lines"] = []
            return journals

        cases = (
            (mock.patch.object(s.h.ledger, "trial_balance", side_effect=lopsided_tb),
             "the books for P1 do not balance (trial balance debits 100.00, credits 99.00, 1 journal(s); journals 100.00 / 100.00, 1 journal(s))"),
            (mock.patch.object(s.h.ledger, "trial_balance", side_effect=miscounted_tb), "trial balance debits 100.00, credits 100.00, 2 journal(s)"),
            (mock.patch.object(s.h, "_period_journals", side_effect=lopsided_journal), f"journal {j['id']} in P1 does not balance (debits 100.00, credits 99.00)"),
            (mock.patch.object(s.h, "_period_journals", side_effect=empty_journal), f"journal {j['id']} in P1 does not balance"),
        )
        for patcher, message in cases:
            with patcher:
                with self.assertRaises(HandoffError) as cm:
                    s.h.prepare_handoff("P1", "owner")
            self.assertIn(message, str(cm.exception))
            self.assertIn("nothing is handed off", str(cm.exception))
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_packages"), 0)
        self.assertEqual([e for e in s.c.audit.entries(entity_type="handoff") if e["action"] == "handoff.prepared"], [])
        # with nothing stubbed the same books hand off
        self.assertEqual(s.h.prepare_handoff("P1", "owner")["total_debit"], "100.00")
        s.assert_books_sound(self)

    def test_write_authority_required(self):
        root = tempfile.mkdtemp()
        live = Scenario(os.path.join(root, "live.sqlite"))
        try:
            live.contribution("500.00")
            h = live.h.prepare_handoff("P1", "owner")
            live.c.snapshot(os.path.join(root, "copy.sqlite"))
            restored = Cipher.open_restored(os.path.join(root, "copy.sqlite"))
            try:
                rh = restored.plugin(PLUGIN_NAME)
                self.assertFalse(restored.db.has_write_authority())
                # the restored package is intact and still verifies
                self.assertEqual(rh.handoff(h["id"])["package_hash"], h["package_hash"])
                self.assertTrue(rh.verify(h["id"])["ok"])
                with self.assertRaises(WriteAuthorityError):
                    rh.record_receipt_details(h["id"], "RCPT-RESTORED-1", "Synthetic Accountant A", "owner")
                with self.assertRaises(WriteAuthorityError):
                    rh.prepare_handoff("P2", "owner")
                self.assertEqual(restored.db.scalar("SELECT COUNT(*) FROM handoff_packages"), 1)
                self.assertEqual(restored.db.scalar("SELECT COUNT(*) FROM handoff_receipt_details"), 0)
                self.assertIsInstance(rh.close_checks("P1"), list)
            finally:
                restored.db.close()
        finally:
            live.c.db.close()


class AcknowledgementTests(unittest.TestCase):
    def test_acknowledge_via_approval(self):
        s = Scenario()
        s.contribution("10000")
        s.expense("1234.56")
        h = s.h.prepare_handoff("P1", "owner")
        with self.assertRaises(HandoffError) as cm:  # no receipt details yet: nothing to approve
            s.request(h["id"])
        self.assertIn("record_receipt_details", str(cm.exception))

        d = s.h.record_receipt_details(h["id"], "  RCPT-SYN-0001 ", "Synthetic Accountant A", "owner")
        self.assertEqual((d["version"], d["receipt_ref"], d["accountant"]), (1, "RCPT-SYN-0001", "Synthetic Accountant A"))
        with self.assertRaises(RoleNotAuthorized):
            s.request(h["id"], role="pm")
        with self.assertRaises(RoleNotAuthorized):
            s.request(h["id"], role="viewer")

        ap = s.request(h["id"])
        m = ap["manifest"]
        self.assertEqual((m["operation"], m["subject"], m["actor_role"], m["entity"], m["currency"]),
                         (OP_ACKNOWLEDGE, {"type": "handoff", "id": h["id"]}, "accountant", ENTITY, "USD"))
        self.assertEqual(m["amounts"], {"package_total_debit": "11234.56", "package_total_credit": "11234.56"})
        b = m["bindings"]
        self.assertEqual((b["package_hash"], b["package_journal_count"], b["receipt_ref"], b["accountant"], b["receipt_details_version"]),
                         (h["package_hash"], 2, "RCPT-SYN-0001", "Synthetic Accountant A", 1))
        self.assertEqual((b["period_status"], b["omission_count"], b["latest_handoff_for_period"], b["label"]), ("open", 0, h["id"], LABEL))
        self.assertEqual(b["period_now"], {"journal_count": 2, "total_debit": "11234.56", "total_credit": "11234.56"})

        with self.assertRaises(RoleNotAuthorized):
            s.c.approve(ap["id"], approver="pm-1", approver_role="pm")
        with self.assertRaises(ApprovalNotGranted):  # nothing executes before a human grants it
            s.c.execute(ap["id"], actor="accountant-1")
        self.assertEqual(s.receipts(), 0)
        s.c.approve(ap["id"], approver="accountant-1", approver_role="accountant")
        done = s.c.execute(ap["id"], actor="accountant-1")
        self.assertFalse(done.replayed)
        r = done.result
        self.assertEqual((r["status"], r["receipt_ref"], r["accountant"], r["package_hash"], r["journal_count"], r["total_debit"], r["omission_count"]),
                         ("acknowledged", "RCPT-SYN-0001", "Synthetic Accountant A", h["package_hash"], 2, "11234.56", 0))
        replay = s.c.execute(ap["id"], actor="accountant-1")
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result, r)
        self.assertEqual(s.receipts(), 1)
        self.assertEqual(s.c.approvals.get(ap["id"])["status"], "consumed")

        hh = s.h.handoff(h["id"])
        self.assertEqual(hh["status"], "acknowledged")
        self.assertEqual((hh["receipt"]["approval_id"], hh["receipt"]["acknowledged_by"], hh["receipt"]["package_hash"]), (ap["id"], "accountant-1", h["package_hash"]))
        self.assertEqual(s.h.close_checks("P1"), [{"check": CHECK_NAME, "ok": True, "detail": s.h.close_checks("P1")[0]["detail"]}])
        self.assertIn("RCPT-SYN-0001", s.h.close_checks("P1")[0]["detail"])

        # duplicates: a second acknowledgement and late receipt details are refused
        with self.assertRaises(HandoffError):
            s.request(h["id"])
        with self.assertRaises(HandoffError):
            s.h.record_receipt_details(h["id"], "RCPT-SYN-0002", "Synthetic Accountant A", "owner")
        actions = [e["action"] for e in s.c.audit.entries(entity_type="handoff", entity_id=h["id"])]
        self.assertEqual(actions, ["handoff.prepared", "handoff.receipt_details_recorded", "handoff.acknowledged"])
        s.assert_books_sound(self)

    def test_controller_and_owner_may_acknowledge_ricky_routes_others(self):
        s = Scenario()
        s.contribution("100")
        h = s.h.prepare_handoff("P1", "owner")
        s.h.record_receipt_details(h["id"], "RCPT-CTL-1", "Synthetic Accountant B", "owner")
        proposal = s.c.ricky.propose(OP_ACKNOWLEDGE, actor_role="accountant", context={"handoff_id": h["id"]})
        self.assertEqual(proposal["decision"], "proposed")
        self.assertEqual(proposal["manifest"]["bindings"]["package_hash"], h["package_hash"])
        self.assertEqual(s.c.ricky.propose(OP_ACKNOWLEDGE, actor_role="pm", context={"handoff_id": h["id"]})["decision"], "abstained")
        self.assertEqual(s.c.ricky.propose(OP_ACKNOWLEDGE, actor_role="treasury", context={"handoff_id": h["id"]})["decision"], "abstained")
        ap = s.grant(h["id"], role="controller")
        self.assertEqual(s.c.execute(ap["id"], actor="controller-1").result["status"], "acknowledged")

    def test_stale_acknowledgement_after_a_later_journal(self):
        s = Scenario()
        s.contribution("10000")
        h1 = s.h.prepare_handoff("P1", "owner")
        s.h.record_receipt_details(h1["id"], "RCPT-SYN-0101", "Synthetic Accountant A", "owner")
        ap = s.grant(h1["id"])
        late = s.expense("75.25")  # posted after the package was prepared
        with self.assertRaises(StaleApprovalError):
            s.c.execute(ap["id"], actor="accountant-1")
        self.assertEqual(s.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(s.receipts(), 0)
        self.assertEqual(s.h.handoff(h1["id"])["status"], "prepared")

        om = s.h.omissions(h1["id"])
        self.assertEqual(([o["journal_id"] for o in om["not_in_package"]], om["reversed_after_package"], om["count"], om["ok"]), ([late["id"]], [], 1, False))
        self.assertEqual(om["not_in_package"][0]["total"], "75.25")
        chk = s.h.close_checks("P1")[0]
        self.assertFalse(chk["ok"])
        self.assertIn(late["id"], chk["detail"])
        self.assertIn("not acknowledged", chk["detail"])

        # a superseding package covers it; the first package's receipt reference cannot be reused
        h2 = s.h.prepare_handoff("P1", "owner")
        self.assertEqual((h2["sequence"], h2["supersedes"], h2["journal_count"], h2["total_debit"]), (2, h1["id"], 2, "10075.25"))
        self.assertTrue(s.h.omissions(h2["id"])["ok"])
        with self.assertRaises(HandoffDuplicate):
            s.h.record_receipt_details(h2["id"], "rcpt-syn-0101", "Synthetic Accountant A", "owner")  # case-insensitive
        s.acknowledge(h2["id"], "RCPT-SYN-0102")
        self.assertTrue(s.h.close_checks("P1")[0]["ok"])
        # the superseded package may still be acknowledged as a fact, under a fresh approval that shows its omission
        ap_old = s.grant(h1["id"])
        self.assertEqual((ap_old["manifest"]["bindings"]["omission_count"], ap_old["manifest"]["bindings"]["latest_handoff_for_period"]), (1, h2["id"]))
        self.assertEqual(s.c.execute(ap_old["id"], actor="accountant-1").result["omission_count"], 1)
        self.assertTrue(s.h.close_checks("P1")[0]["ok"])  # judged on the latest hand-off
        s.assert_books_sound(self)

    def test_receipt_details_change_invalidates_and_duplicates_are_refused(self):
        s = Scenario()
        s.contribution("100")
        h = s.h.prepare_handoff("P1", "owner")
        s.h.record_receipt_details(h["id"], "RCPT-SYN-0201", "Synthetic Accountant A", "owner")
        with self.assertRaises(HandoffDuplicate):
            s.h.record_receipt_details(h["id"], "RCPT-SYN-0201", "Synthetic Accountant A", "owner")
        ap = s.grant(h["id"])
        d2 = s.h.record_receipt_details(h["id"], "RCPT-SYN-0201", "Synthetic Accountant C", "owner")
        self.assertEqual(d2["version"], 2)
        self.assertEqual(s.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            s.c.execute(ap["id"], actor="accountant-1")
        ap2 = s.grant(h["id"])
        self.assertEqual((ap2["manifest"]["bindings"]["accountant"], ap2["manifest"]["bindings"]["receipt_details_version"]), ("Synthetic Accountant C", 2))
        self.assertEqual(s.c.execute(ap2["id"], actor="accountant-1").result["accountant"], "Synthetic Accountant C")

        # another hand-off cannot claim the same receipt reference
        s.contribution("50", period="P2")
        other = s.h.prepare_handoff("P2", "owner")
        with self.assertRaises(HandoffDuplicate):
            s.h.record_receipt_details(other["id"], "RCPT-SYN-0201", "Synthetic Accountant C", "owner")

    def test_receipt_references_are_caseless_across_unicode(self):
        s = Scenario()
        s.contribution("100")
        s.contribution("50", period="P2")
        h1 = s.h.prepare_handoff("P1", "owner")
        h2 = s.h.prepare_handoff("P2", "owner")
        s.h.record_receipt_details(h1["id"], "RCPT-É-1", "Synthetic Accountant A", "owner")
        # lower case, decomposed accent, full-width letters: all the same reference as on h1
        for variant in ("rcpt-é-1", "RCPT-É-1", "rcpt-é-1", "ＲＣＰＴ-É-1"):
            with self.assertRaises(HandoffDuplicate) as cm:
                s.h.record_receipt_details(h2["id"], variant, "Synthetic Accountant A", "owner")
            self.assertIn(h1["id"], str(cm.exception))
        self.assertEqual(ref_key("Straße-1"), ref_key("STRASSE-1"))
        self.assertNotEqual(ref_key("RCPT-É-1"), ref_key("RCPT-E-1"))
        # the database applies the same rule to raw rows: NOCASE alone folds ASCII letters only, so these
        # (lower-case accent, decomposed accent, full-width letters) are refused by the Unicode guard ...
        unicode_only = ("rcpt-é-1", "RCPT-É-1", "rcpt-é-1", "ＲＣＰＴ-É-1")
        for n, variant in enumerate(unicode_only + ("rcpt-É-1", "RCPT-É-1")):
            with self.assertRaises(sqlite3.DatabaseError) as cm:
                s.c.db.execute(RAW_DETAILS, (f"hrd_raw_{n}", h2["id"], 1, variant, "Synthetic Accountant A", RAW_TIME))
            self.assertIn("a receipt reference belongs to one hand-off only", str(cm.exception))
            if variant in unicode_only:
                self.assertIn("compared caseless across Unicode", str(cm.exception))
        # ... and ASCII case alone was already refused by the original guard (either message is the refusal)
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_receipt_details WHERE handoff_id=?", (h2["id"],)), 0)
        self.assertEqual(s.h.record_receipt_details(h2["id"], "RCPT-E-1", "Synthetic Accountant A", "owner")["version"], 1)  # unaccented: distinct
        # re-casing the reference on its own hand-off is a correction (a new version), not a clash
        self.assertEqual(s.h.record_receipt_details(h1["id"], "rcpt-é-1", "Synthetic Accountant A", "owner")["version"], 2)
        # the guard is selective: a raw row with a reference of its own is not refused by it
        s.c.db.execute(RAW_DETAILS, ("hrd_raw_distinct", h2["id"], 2, "RCPT-RAW-DISTINCT-1", "Synthetic Accountant A", RAW_TIME))
        self.assertEqual(s.c.db.scalar("SELECT MAX(version) FROM handoff_receipt_details WHERE handoff_id=?", (h2["id"],)), 2)

    def test_receipt_reference_guard_fails_closed_without_the_sql_function(self):
        path = os.path.join(tempfile.mkdtemp(), "handoff-raw.sqlite")
        s = Scenario(path)
        try:
            s.contribution("100.00")
            h = s.h.prepare_handoff("P1", "owner")
            raw = sqlite3.connect(path, isolation_level=None)
            try:  # a connection that never registered handoff_ref_key cannot add receipt details at all
                with self.assertRaises(sqlite3.OperationalError) as cm:
                    raw.execute(RAW_DETAILS, ("hrd_raw_plain", h["id"], 1, "RCPT-PLAIN-1", "Synthetic Accountant A", RAW_TIME))
                self.assertIn("handoff_ref_key", str(cm.exception))
            finally:
                raw.close()
            self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_receipt_details"), 0)
            self.assertEqual(s.h.record_receipt_details(h["id"], "RCPT-PLAIN-1", "Synthetic Accountant A", "owner")["version"], 1)
        finally:
            s.c.db.close()

    def test_a_stale_approval_forced_through_the_core_api_records_nothing(self):
        s = Scenario()
        s.contribution("10000")
        h = s.h.prepare_handoff("P1", "owner")
        d = s.h.record_receipt_details(h["id"], "RCPT-SYN-1001", "Synthetic Accountant A", "owner")
        pending = s.request(h["id"])
        with self.assertRaises(HandoffError) as cm:  # never under an approval that was not consumed
            s.h.apply(OP_ACKNOWLEDGE, h["id"], approval_id=pending["id"], manifest=pending["manifest"], actor="accountant-1", period_id=None)
        self.assertNotIsInstance(cm.exception, HandoffStale)
        self.assertIn("is pending", str(cm.exception))
        s.c.approve(pending["id"], approver="accountant-1", approver_role="accountant")
        stored = s.c.approvals.get(pending["id"])["manifest"]
        s.expense("5.00")  # the approval is now stale

        # misuse of the public core API: consume with the approval's own stored manifest, then apply directly
        s.c.approvals.consume(pending["id"], current_manifest=stored, consumer="accountant-1")
        with self.assertRaises(HandoffError) as cm:
            s.h.apply(OP_ACKNOWLEDGE, h["id"], approval_id=pending["id"], manifest=stored, actor="owner", period_id=None)
        self.assertIn("was consumed by accountant-1", str(cm.exception))
        with self.assertRaises(HandoffStale) as cm:
            s.h.apply(OP_ACKNOWLEDGE, h["id"], approval_id=pending["id"], manifest=stored, actor="accountant-1", period_id=None)
        self.assertIn("changed after the acknowledgement was approved", str(cm.exception))
        # the database refuses the receipt too, whatever omission count or actor a raw insert claims
        for count, actor, message in ((0, "accountant-1", "no longer hold"), (1, "accountant-1", "carries exactly the facts its approval bound"),
                                      (0, "someone-else", "who consumed its approval")):
            with self.assertRaises(sqlite3.DatabaseError) as cm:
                raw_receipt(s, h, d, pending["id"], omission_count=count, acknowledged_by=actor)
            self.assertIn(message, str(cm.exception))
        self.assertEqual(s.receipts(), 0)
        self.assertEqual(s.h.handoff(h["id"])["status"], "prepared")
        self.assertFalse(s.h.close_checks("P1")[0]["ok"])
        s.assert_books_sound(self)

    def test_a_reversal_in_another_period_blocks_a_forced_receipt(self):
        s = Scenario()
        j = s.contribution("10000")
        h = s.h.prepare_handoff("P1", "owner")
        d = s.h.record_receipt_details(h["id"], "RCPT-SYN-1101", "Synthetic Accountant A", "owner")
        ap = s.grant(h["id"])
        stored = s.c.approvals.get(ap["id"])["manifest"]
        s.c.ledger.reverse(j["id"], period_id="P2", posted_by="owner", reason="synthetic correction")  # P1's own figures do not move
        self.assertEqual(s.h._period_now("P1"), stored["bindings"]["period_now"])
        s.c.approvals.consume(ap["id"], current_manifest=stored, consumer="accountant-1")
        with self.assertRaises(HandoffStale):
            s.h.apply(OP_ACKNOWLEDGE, h["id"], approval_id=ap["id"], manifest=stored, actor="accountant-1", period_id=None)
        with self.assertRaises(sqlite3.DatabaseError) as cm:  # the bound count of 0 is no longer the true count
            raw_receipt(s, h, d, ap["id"], omission_count=0)
        self.assertIn("true omission count", str(cm.exception))
        with self.assertRaises(sqlite3.DatabaseError) as cm:  # and the true count is not what the approval bound
            raw_receipt(s, h, d, ap["id"], omission_count=1)
        self.assertIn("carries exactly the facts its approval bound", str(cm.exception))
        self.assertEqual(s.receipts(), 0)

    def test_superseding_package_invalidates_a_granted_acknowledgement(self):
        s = Scenario(with_p0=True)
        j = s.contribution("900.00")
        h1 = s.h.prepare_handoff("P1", "owner")
        s.h.record_receipt_details(h1["id"], "RCPT-SYN-0301", "Synthetic Accountant A", "owner")
        ap = s.grant(h1["id"])
        s.subledgers("P0")  # AP and AR change; P1's journals do not
        self.assertTrue(s.h.omissions(h1["id"])["ok"])
        h2 = s.h.prepare_handoff("P1", "owner")
        self.assertEqual(h2["package"]["journals"][0]["id"], j["id"])
        self.assertEqual(h2["package"]["ap"]["subledger_total"], "18000.00")
        self.assertEqual(s.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            s.c.execute(ap["id"], actor="accountant-1")
        self.assertEqual(s.receipts(), 0)

    def test_period_closed_between_grant_and_execution(self):
        s = Scenario()
        s.contribution("100")
        h = s.h.prepare_handoff("P1", "owner")
        s.h.record_receipt_details(h["id"], "RCPT-SYN-0401", "Synthetic Accountant A", "owner")
        ap = s.grant(h["id"])
        s.c.close_period("P1")  # low-level fixture close, outside the checklist
        with self.assertRaises(StaleApprovalError):
            s.c.execute(ap["id"], actor="accountant-1")
        self.assertEqual(s.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(HandoffError):
            s.request(h["id"])
        with self.assertRaises(HandoffError):
            s.h.record_receipt_details(h["id"], "RCPT-SYN-0402", "Synthetic Accountant A", "owner")
        self.assertEqual(s.receipts(), 0)


class OmissionAndCloseTests(unittest.TestCase):
    def test_reversals_after_the_package_are_omissions(self):
        s = Scenario()
        j1 = s.contribution("10000")
        j2 = s.expense("400.00")
        h = s.h.prepare_handoff("P1", "owner")
        self.assertTrue(s.h.omissions(h["id"])["ok"])

        r2 = s.c.ledger.reverse(j2["id"], period_id="P2", posted_by="owner", reason="synthetic correction")
        om = s.h.omissions(h["id"])
        self.assertEqual(om["not_in_package"], [])  # the reversal sits in P2
        self.assertEqual([(o["journal_id"], o["reversal_journal_id"], o["reversal_period_id"]) for o in om["reversed_after_package"]], [(j2["id"], r2["id"], "P2")])
        self.assertEqual(om["count"], 1)
        self.assertIn("reversed later", s.h.close_checks("P1")[0]["detail"])

        r1 = s.c.ledger.reverse(j1["id"], period_id="P1", posted_by="owner", reason="synthetic correction in period")
        om = s.h.omissions(h["id"])
        self.assertEqual([o["journal_id"] for o in om["not_in_package"]], [r1["id"]])
        self.assertEqual(om["not_in_package"][0]["reversal_of"], j1["id"])
        self.assertEqual(sorted(o["journal_id"] for o in om["reversed_after_package"]), sorted([j1["id"], j2["id"]]))
        self.assertEqual(om["count"], 3)

        # a new package records the reversals as known: no omissions
        h2 = s.h.prepare_handoff("P1", "owner")
        self.assertEqual({j["id"]: j["reversed_by"] for j in h2["package"]["journals"]}, {j1["id"]: r1["id"], j2["id"]: r2["id"], r1["id"]: None})
        self.assertTrue(s.h.omissions(h2["id"])["ok"])
        self.assertEqual(h2["package"]["csv"]["journals.csv"].count(r2["id"]), 2)  # reversed_by on both lines of j2
        s.assert_books_sound(self)

    def test_close_check_behavior(self):
        s = Scenario()
        self.assertEqual(s.h.close_checks("P1"), [{"check": CHECK_NAME, "ok": True,
                                                   "detail": "no shadow hand-off prepared for P1; the hand-off is optional in the prototype (informational)"}])
        s.contribution("100")
        h = s.h.prepare_handoff("P1", "owner")
        chk = s.h.close_checks("P1")
        self.assertEqual(len(chk), 1)
        self.assertEqual(set(chk[0]), {"check", "ok", "detail"})
        self.assertFalse(chk[0]["ok"])
        self.assertIn(h["id"], chk[0]["detail"])
        self.assertIn("not acknowledged", chk[0]["detail"])
        self.assertEqual(chk, s.h.close_checks("P1"))  # deterministic: the close approval binds the checklist hash
        self.assertTrue(s.h.close_checks("P2")[0]["ok"])  # another period is unaffected
        brief = s.c.ricky.brief(s.pid, actor_role="owner")
        self.assertTrue(any(CHECK_NAME in it["text"] for it in brief["items"]))
        s.acknowledge(h["id"], "RCPT-SYN-0501")
        self.assertTrue(s.h.close_checks("P1")[0]["ok"])

    def test_close_module_waits_for_the_receipt(self):
        s = Scenario(keep=("handoff", "close"))
        if "close" not in s.c._plugins:
            self.skipTest("close module not registered")
        from apps.cipher.domain.close import CloseError
        cl = s.c.plugin("close")
        s.contribution("2500.00")
        self.assertIn(CHECK_NAME, [c["check"] for c in cl.checklist("P1")])
        self.assertTrue(cl.checklist_report("P1")["all_ok"])  # optional: no hand-off, no block
        h = s.h.prepare_handoff("P1", "owner")
        self.assertEqual(cl.checklist_report("P1")["failing"], [CHECK_NAME])
        with self.assertRaises(CloseError):
            s.c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(s.c.ledger.period("P1")["status"], "open")
        s.acknowledge(h["id"], "RCPT-SYN-0601")
        self.assertTrue(cl.checklist_report("P1")["all_ok"])
        s.c.approve_and_execute("close.close_period", "P1")
        self.assertEqual(s.c.ledger.period("P1")["status"], "closed")
        with self.assertRaises(HandoffError):
            s.h.prepare_handoff("P1", "owner")
        s.assert_books_sound(self)


class ImmutabilityAndExportTests(unittest.TestCase):
    def test_package_rows_are_immutable(self):
        s = Scenario()
        s.contribution("10000")
        h = s.h.prepare_handoff("P1", "owner")
        for sql in ("UPDATE handoff_packages SET total_debit='1.00' WHERE id=?", "UPDATE handoff_packages SET package_json='{}' WHERE id=?",
                    "DELETE FROM handoff_packages WHERE id=?"):
            with self.assertRaises(sqlite3.DatabaseError) as cm:
                s.c.db.execute(sql, (h["id"],))
            self.assertIn("immutable", str(cm.exception))
        # a raw package must take the next sequence, balance and carry the label
        with self.assertRaises(sqlite3.DatabaseError):
            s.c.db.execute("""INSERT INTO handoff_packages (id, period_id, sequence, label, format, package_json, package_hash, journal_count, total_debit,
                              total_credit, supersedes, prepared_by, prepared_at) VALUES ('hof_raw','P1',1,?,?,'{}',?,0,'0.00','0.00',NULL,'x','t')""",
                           (LABEL, FORMAT, "0" * 64))
        with self.assertRaises(sqlite3.DatabaseError):
            s.c.db.execute("""INSERT INTO handoff_packages (id, period_id, sequence, label, format, package_json, package_hash, journal_count, total_debit,
                              total_credit, supersedes, prepared_by, prepared_at) VALUES ('hof_raw','P1',2,'authoritative books',?,'{}',?,0,'0.00','0.00',?,'x','t')""",
                           (FORMAT, "0" * 64, h["id"]))

        # a raw receipt without a consumed acknowledgement approval is refused
        d = s.h.record_receipt_details(h["id"], "RCPT-SYN-0701", "Synthetic Accountant A", "owner")
        pending = s.request(h["id"])
        with self.assertRaises(sqlite3.DatabaseError) as cm:
            s.c.db.execute("""INSERT INTO handoff_receipts (id, handoff_id, receipt_details_id, receipt_ref, accountant, package_hash, journal_count, total_debit,
                              total_credit, omission_count, approval_id, acknowledged_by, acknowledged_at) VALUES ('hrc_raw',?,?,?,?,?,1,'10000.00','10000.00',0,?,'x','t')""",
                           (h["id"], d["id"], d["receipt_ref"], d["accountant"], h["package_hash"], pending["id"]))
        self.assertIn("consumed handoff.acknowledge approval", str(cm.exception))
        with self.assertRaises(sqlite3.DatabaseError) as cm:
            s.c.db.execute("UPDATE handoff_receipt_details SET accountant='someone else' WHERE id=?", (d["id"],))
        self.assertIn("receipt details are immutable; record a new version", str(cm.exception))
        with self.assertRaises(sqlite3.DatabaseError) as cm:
            s.c.db.execute("DELETE FROM handoff_receipt_details WHERE id=?", (d["id"],))
        self.assertIn("receipt details are immutable and never deleted", str(cm.exception))
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_receipt_details WHERE id=?", (d["id"],)), 1)

        # the snapshot does not follow the books
        before = s.h.package(h["id"])
        s.expense("10.00")
        self.assertEqual(s.h.package(h["id"]), before)
        self.assertEqual(s.h.handoff(h["id"])["package_hash"], h["package_hash"])
        self.assertTrue(s.h.verify(h["id"])["ok"])

        s.c.approve(pending["id"], approver="accountant-1", approver_role="accountant")
        with self.assertRaises(StaleApprovalError):  # bound before the 10.00 journal
            s.c.execute(pending["id"], actor="accountant-1")
        h2 = s.h.prepare_handoff("P1", "owner")
        s.acknowledge(h2["id"], "RCPT-SYN-0702")
        with self.assertRaises(sqlite3.DatabaseError):
            s.c.db.execute("UPDATE handoff_receipts SET receipt_ref='RCPT-OTHER' WHERE handoff_id=?", (h2["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            s.c.db.execute("DELETE FROM handoff_receipts WHERE handoff_id=?", (h2["id"],))
        self.assertEqual(s.receipts(), 1)

    def test_forged_raw_packages_are_refused_by_the_database(self):
        s = Scenario()
        s.contribution("10000")
        s.expense("1234.56")
        h = s.h.prepare_handoff("P1", "owner")
        real = s.h.package(h["id"])

        def refused(message, **over):
            with self.assertRaises(sqlite3.DatabaseError) as cm:
                forge(s, h, **over)
            self.assertIn(message, str(cm.exception))

        # the review's probe: header 1.00 / 0 journals over the real JSON (real journal ids) and its correct hash
        refused("header must agree with its own content", journal_count=0, total_debit="1.00", total_credit="1.00")
        # the JSON forged to agree with that header: the books still have 2 journals
        empty = {**real, "journal_count": 0, "journals": [], "totals": {"debit": "1.00", "credit": "1.00"},
                 "trial_balance": {**real["trial_balance"], "journal_count": 0, "total_debit": "1.00", "total_credit": "1.00"}}
        refused("lists exactly the journals of its period", package_json=canonical_json(empty), journal_count=0, total_debit="1.00", total_credit="1.00")
        # every journal listed but the totals understated everywhere: the books total 11234.56
        under = {**real, "totals": {"debit": "1.00", "credit": "1.00"},
                 "trial_balance": {**real["trial_balance"], "total_debit": "1.00", "total_credit": "1.00"}}
        refused("carries the journal totals of its period", package_json=canonical_json(under), total_debit="1.00", total_credit="1.00")
        # one journal listed twice in place of the other
        twice = {**real, "journals": [real["journals"][0], real["journals"][0]]}
        refused("lists exactly the journals of its period", package_json=canonical_json(twice))
        refused("cipher-handoff/1 format", format="other/9")
        refused("64 lowercase hexadecimal", package_hash="z" * 64)
        refused("64 lowercase hexadecimal", package_hash=h["package_hash"].upper())
        refused("canonical money totals", total_debit="11234.560", total_credit="11234.560")
        refused("canonical money totals", total_debit="011234.56", total_credit="011234.56")
        refused("JSON object listing its journals", package_json="not json")
        refused("JSON object listing its journals", package_json=canonical_json([real]))
        # the base guard keeps its own messages
        refused("SHADOW label", label="authoritative books")
        refused("next sequence", sequence=1)
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM handoff_packages"), 1)
        self.assertTrue(s.h.verify(h["id"])["ok"])

    def test_forged_packages_the_database_cannot_judge_never_pass(self):
        s = Scenario()
        j1 = s.contribution("10000")
        s.expense("1234.56")
        h = s.h.prepare_handoff("P1", "owner")
        s.acknowledge(h["id"], "RCPT-SYN-0901")
        self.assertTrue(s.h.close_checks("P1")[0]["ok"])
        real = s.h.package(h["id"])

        # SQLite cannot compute SHA-256: a raw row whose hash does not match its (otherwise true) JSON is stored ...
        # (every forgery here also gets a correctly chained audit entry, as the strongest raw writer would add,
        # so each content check is seen on its own)
        bad_hash = forge(s, h, package_hash="f" * 64)
        v = s.h.verify(bad_hash["id"])
        self.assertEqual((v["ok"], v["integrity_problems"]), (False, ["its hash does not match the stored package"]))
        # ... and becomes the latest package, which the close check judges and refuses
        chk = s.h.close_checks("P1")[0]
        self.assertFalse(chk["ok"])
        self.assertIn(f"latest hand-off {bad_hash['id']}", chk["detail"])
        self.assertIn("fails its integrity check (its hash does not match the stored package)", chk["detail"])
        self.assertEqual(s.h.omissions(bad_hash["id"])["count"], 0)  # omissions alone would not have caught it
        s.h.record_receipt_details(bad_hash["id"], "RCPT-SYN-0902", "Synthetic Accountant A", "owner")
        with self.assertRaises(HandoffError) as cm:  # nothing to approve
            s.request(bad_hash["id"])
        self.assertIn("fails its integrity check", str(cm.exception))
        with self.assertRaises(HandoffRefused) as cm:  # at any transaction depth
            with s.c.db.transaction():
                s.request(bad_hash["id"])
        self.assertIn("fails its integrity check", str(cm.exception))
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM approvals WHERE subject_id=?", (bad_hash["id"],)), 0)

        # correct hashes over tampered content: each tamper is named
        tampered_csv = {**real, "csv": {**real["csv"], "journals.csv": real["csv"]["journals.csv"].replace("10000.00", "1.00")}}
        t1 = forge(s, bad_hash, package_json=canonical_json(tampered_csv))
        self.assertEqual(s.h.verify(t1["id"])["integrity_problems"], ["its journals.csv does not match its content"])
        edited = json.loads(canonical_json(real))
        edited["journals"][0]["lines"][0]["memo"] = "edited after the fact"
        t2 = forge(s, t1, package_json=canonical_json(edited))
        self.assertEqual(s.h.verify(t2["id"])["integrity_problems"],
                         [f"package journal {j1['id']} does not match the books", "its journals.csv does not match its content"])
        moved = json.loads(canonical_json(real))
        moved["trial_balance"]["rows"][0]["code"] = "9999"
        t3 = forge(s, t2, package_json=canonical_json(moved))
        self.assertEqual(s.h.verify(t3["id"])["integrity_problems"], ["its trial balance rows do not agree with its journal lines"])
        shifted = json.loads(canonical_json(real))
        shifted["journals"][0]["total_debit"] = "9999.00"
        t4 = forge(s, t3, package_json=canonical_json(shifted))
        self.assertEqual(s.h.verify(t4["id"])["integrity_problems"],
                         [f"package journal {j1['id']} does not add up (lines 10000.00 / 10000.00, stated 9999.00 / 10000.00)"])
        for forged in (t1, t2, t3, t4):
            self.assertFalse(s.h.handoff(forged["id"])["integrity_ok"])
        self.assertIn("fails its integrity check", s.h.close_checks("P1")[0]["detail"])

        # a real package supersedes the forgeries; a forgery inserted after its approval was granted makes it stale
        h2 = s.h.prepare_handoff("P1", "owner")
        self.assertEqual((h2["sequence"], h2["supersedes"], h2["integrity_ok"], h2["package_hash"]), (7, t4["id"], True, h["package_hash"]))
        s.h.record_receipt_details(h2["id"], "RCPT-SYN-0903", "Synthetic Accountant A", "owner")
        ap = s.grant(h2["id"])
        late_forgery = forge(s, h2, package_hash="e" * 64)
        with self.assertRaises(StaleApprovalError):
            s.c.execute(ap["id"], actor="accountant-1")
        self.assertEqual(s.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertIn(late_forgery["id"], s.h.close_checks("P1")[0]["detail"])
        h3 = s.h.prepare_handoff("P1", "owner")
        s.acknowledge(h3["id"], "RCPT-SYN-0904")
        self.assertTrue(s.h.close_checks("P1")[0]["ok"])

        st = s.h.state(s.pid)
        self.assertEqual((st["handoff_count"], st["failing_integrity"]), (9, 6))
        export = {p["id"]: p["integrity_problems"] for p in s.h.audit_export()["packages"]}
        self.assertEqual([hid for hid, problems in export.items() if problems],
                         [bad_hash["id"], t1["id"], t2["id"], t3["id"], t4["id"], late_forgery["id"]])
        self.assertEqual(s.receipts(), 2)
        s.assert_books_sound(self)

    def test_invented_subledgers_need_the_audit_entry_prepare_handoff_records(self):
        """The review's probes: AP / AR open items and reconciliations cannot be re-derived from the books
        later, so a raw row carrying invented ones (correct SHA-256, CSV re-rendered) fails on provenance;
        an invented reversal or account name fails against the books; an approval that bound integrity
        problems can record no receipt, through ``apply`` or a raw row."""
        s = Scenario(with_p0=True)
        s.subledgers("P0")
        j1 = s.contribution("10000")
        h = s.h.prepare_handoff("P1", "owner")
        s.acknowledge(h["id"], "RCPT-SYN-1301")
        self.assertTrue(s.h.close_checks("P1")[0]["ok"])
        real = s.h.package(h["id"])

        # probe 1: nothing owed either way, everything reconciled; the content agrees with itself throughout
        invented = json.loads(canonical_json(real))
        for side in ("ap", "ar"):
            invented[side]["items"] = [{**it, "open": "0.00"} for it in invented[side]["items"]] if side == "ap" else []
            invented[side].update({"subledger_total": "0.00", "reconciled": True})
            invented["reconciliations"][side] = {"subledger_total": "0.00", "control_balance": invented[side]["control_balance"], "reconciled": True}
        for label, value in invented["reconciliations"].items():
            if label not in ("ap", "ar"):
                invented["reconciliations"][label] = {**value, "reconciled": True}
        invented["csv"] = _csv_files("P1", invented["journals"], invented["ap"]["items"], invented["ar"]["items"])
        f1 = forge(s, h, package_json=canonical_json(invented), audit=None)
        v = s.h.verify(f1["id"])
        self.assertEqual((v["ok"], v["recomputed"] == f1["package_hash"], v["integrity_problems"]), (False, True, [NO_AUDIT_ENTRY]))
        self.assertEqual(s.h.omissions(f1["id"])["count"], 0)  # the journals are the real ones
        s.h.record_receipt_details(f1["id"], "RCPT-SYN-1302", "Synthetic Accountant A", "owner")
        for depth in ("outside", "inside"):
            with self.assertRaises(HandoffRefused) as cm:
                if depth == "inside":
                    with s.c.db.transaction():
                        s.request(f1["id"])
                else:
                    s.request(f1["id"])
            self.assertIn(NO_AUDIT_ENTRY, str(cm.exception))
        self.assertEqual(s.c.db.scalar("SELECT COUNT(*) FROM approvals WHERE subject_id=?", (f1["id"],)), 0)
        chk = s.h.close_checks("P1")[0]
        self.assertFalse(chk["ok"])
        self.assertIn(f"latest hand-off {f1['id']}", chk["detail"])
        self.assertIn(NO_AUDIT_ENTRY, chk["detail"])

        # the same forgery with an audit entry that records another package's hash
        f2 = forge(s, f1, package_json=canonical_json(invented), audit="mismatched")
        self.assertEqual(s.h.verify(f2["id"])["integrity_problems"], [AUDIT_MISMATCH])

        # probe 2: an invented reversal and account name (CSV re-rendered to match), correctly chained audit entry
        renamed = json.loads(canonical_json(real))
        renamed["journals"][0]["reversed_by"] = "jrn_fictional_reversal"
        renamed["journals"][0]["lines"][0]["account_name"] = "Synthetic forged account name"
        renamed["csv"] = _csv_files("P1", renamed["journals"], renamed["ap"]["items"], renamed["ar"]["items"])
        f3 = forge(s, f2, package_json=canonical_json(renamed))
        self.assertEqual(s.h.verify(f3["id"])["integrity_problems"], [
            f"package journal {j1['id']} does not match the books",
            f"package journal {j1['id']} records reversal jrn_fictional_reversal that the books do not have",
        ])
        self.assertEqual(s.h.omissions(f3["id"])["count"], 0)  # omissions alone would not have caught it

        # period facts, currency and a reconciliation that no longer repeats its section
        restated = json.loads(canonical_json(real))
        restated["period"]["name"] = "Synthetic forged period name"
        restated["currency"] = "EUR"
        restated["reconciliations"]["ap"]["reconciled"] = False
        f4 = forge(s, f3, package_json=canonical_json(restated))
        self.assertEqual(s.h.verify(f4["id"])["integrity_problems"], [
            "its period facts do not match period P1 in the books",
            "its currency or open-items basis is not this module's (USD; open items as at preparation)",
            "its AP reconciliation does not repeat its AP open items section",
        ])

        # an approval that bound f4's integrity problems (a manifest built around the proposal refusal) records nothing
        d4 = s.h.record_receipt_details(f4["id"], "RCPT-SYN-1304", "Synthetic Accountant A", "owner")
        problems = s.h.verify(f4["id"])["integrity_problems"]
        with mock.patch.object(s.h, "_integrity", return_value=[]):
            m = s.h.manifest_for(OP_ACKNOWLEDGE, f4["id"], actor_role="accountant")
        m["bindings"]["package_integrity_problems"] = problems
        forced = s.c.approvals.request(m, requested_by="owner")
        s.c.approve(forced["id"], approver="accountant-1", approver_role="accountant")
        s.c.approvals.consume(forced["id"], current_manifest=m, consumer="accountant-1")
        with self.assertRaises(HandoffStale) as cm:
            s.h.apply(OP_ACKNOWLEDGE, f4["id"], approval_id=forced["id"], manifest=m, actor="accountant-1", period_id=None)
        self.assertIn("fails its integrity check", str(cm.exception))
        with self.assertRaises(sqlite3.DatabaseError) as cm:  # every other bound fact holds; the bound problems do not
            raw_receipt(s, f4, d4, forced["id"], omission_count=0)
        self.assertIn("needs an approval that bound a package with no integrity problems", str(cm.exception))
        self.assertEqual((s.receipts(), s.h.handoff(f4["id"])["status"]), (1, "prepared"))

        # a real package supersedes the forgeries and is acknowledged normally
        h2 = s.h.prepare_handoff("P1", "owner")
        self.assertEqual((h2["integrity_ok"], h2["package_hash"], h2["supersedes"]), (True, h["package_hash"], f4["id"]))
        s.acknowledge(h2["id"], "RCPT-SYN-1305")
        self.assertTrue(s.h.close_checks("P1")[0]["ok"])
        self.assertEqual(s.h.state(s.pid)["failing_integrity"], 4)
        s.assert_books_sound(self)

        # last, because it breaks the audit chain: an audit entry whose own hash is wrong
        f5 = forge(s, h2, audit="broken")
        self.assertEqual(s.h.verify(f5["id"])["integrity_problems"], [AUDIT_BROKEN])
        self.assertFalse(s.c.audit.verify_chain()["ok"])
        self.assertFalse(s.h.close_checks("P1")[0]["ok"])

    def test_workspace_with_the_original_handoff_schema_upgrades_in_place(self):
        """A file-backed workspace created before the integrity and acknowledgement guards existed keeps its
        packages and receipts, and gains the guards on reopening (applied catalog entries are append-only)."""
        from apps.cipher.core import db as core_db
        path = os.path.join(tempfile.mkdtemp(), "handoff-upgrade.sqlite")
        guards = (GUARDS_SCHEMA_NAME, ACK_GUARDS_SCHEMA_NAME)
        legacy_catalog = [entry for entry in core_db.SCHEMA_CATALOG if entry[1] not in guards]
        with mock.patch.object(core_db, "SCHEMA_CATALOG", legacy_catalog):
            old = Scenario(path)
            try:
                applied = [v["name"] for v in old.c.db.schema_status()["versions"]]
                self.assertFalse(set(guards) & set(applied))
                old.contribution("700.00")
                h = old.h.prepare_handoff("P1", "owner")
                old.acknowledge(h["id"], "RCPT-SYN-1201")
            finally:
                old.c.db.close()
        c = Cipher(path)
        try:
            status = c.db.schema_status()
            self.assertEqual(status["pending"], [])
            applied = [v["name"] for v in status["versions"] if v["applied"]]
            self.assertTrue(set(guards) <= set(applied))
            self.assertLess(applied.index(GUARDS_SCHEMA_NAME), applied.index(ACK_GUARDS_SCHEMA_NAME))
            hp = c.plugin(PLUGIN_NAME)
            self.assertTrue(hp.verify(h["id"])["ok"])
            self.assertEqual(hp.handoff(h["id"])["status"], "acknowledged")
            self.assertTrue(hp.close_checks("P1")[0]["ok"])
            with self.assertRaises(sqlite3.DatabaseError) as cm:  # the upgraded workspace refuses the review's forgery
                c.db.execute("""INSERT INTO handoff_packages (id, period_id, sequence, label, format, package_json, package_hash, journal_count, total_debit,
                                total_credit, supersedes, prepared_by, prepared_at) SELECT 'hof_raw_up', period_id, 2, label, format, package_json, package_hash, 0,
                                '1.00', '1.00', id, 'raw', ? FROM handoff_packages WHERE id=?""", (RAW_TIME, h["id"]))
            self.assertIn("header must agree with its own content", str(cm.exception))
            self.assertTrue(c.audit.verify_chain()["ok"])
        finally:
            c.db.close()

    def test_state_audit_export_and_schema(self):
        s = Scenario()
        s.contribution("10000")
        h1 = s.h.prepare_handoff("P1", "owner")
        s.acknowledge(h1["id"], "RCPT-SYN-0801")
        late = s.expense("12.34")
        st = s.h.state(s.pid)
        json.dumps(st)
        self.assertEqual((st["label"], st["scope"], st["handoff_count"], st["unacknowledged"], st["with_omissions"], st["failing_integrity"]),
                         (LABEL, "entity", 1, 0, 1, 0))
        p1 = next(p for p in st["periods"] if p["period_id"] == "P1")
        self.assertEqual(len(p1["handoffs"]), 1)
        row = p1["handoffs"][0]
        self.assertEqual((row["id"], row["status"], row["omission_count"], row["receipt_ref"], row["is_latest"]), (h1["id"], "acknowledged", 1, "RCPT-SYN-0801", True))
        self.assertFalse(p1["close_check"]["ok"])
        self.assertIn(late["id"], p1["close_check"]["detail"])
        p2 = next(p for p in st["periods"] if p["period_id"] == "P2")
        self.assertEqual((p2["handoffs"], p2["latest"], p2["close_check"]["ok"]), ([], None, True))
        self.assertEqual(s.c.project_state(s.pid)[PLUGIN_NAME]["handoff_count"], 1)
        self.assertEqual([x["id"] for x in s.h.handoffs("P1")], [h1["id"]])

        export = s.c.audit_export()
        json.dumps(export)
        mod = export["modules"][PLUGIN_NAME]
        self.assertNotIn("error", mod)
        self.assertEqual(len(mod["packages"]), 1)
        pkg = mod["packages"][0]
        self.assertTrue(pkg["hash_verified"])
        self.assertEqual(pkg["integrity_problems"], [])  # a later journal is an omission, not an integrity failure
        self.assertEqual(sha256_hex(pkg["package_json"]), h1["package_hash"])
        self.assertEqual([r["receipt_ref"] for r in mod["receipts"]], ["RCPT-SYN-0801"])
        self.assertEqual(mod["omissions"], [{"handoff_id": h1["id"], "period_id": "P1", "sequence": 1, "count": 1, "not_in_package": [late["id"]],
                                             "reversed_after_package": [], "missing_from_books": []}])
        status = s.c.db.schema_status()
        names = [v["name"] for v in status["versions"]]
        self.assertIn(SCHEMA_NAME, names)
        self.assertIn(GUARDS_SCHEMA_NAME, names)
        self.assertIn(ACK_GUARDS_SCHEMA_NAME, names)
        # the guards sit after the tables they guard
        self.assertLess(names.index(SCHEMA_NAME), names.index(GUARDS_SCHEMA_NAME))
        self.assertLess(names.index(GUARDS_SCHEMA_NAME), names.index(ACK_GUARDS_SCHEMA_NAME))
        self.assertEqual(status["pending"], [])
        triggers = {r["name"] for r in s.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertTrue({"handoff_packages_content_guard", "handoff_receipts_binding_guard", "handoff_receipts_integrity_guard",
                         "handoff_receipt_details_unicode_ref_guard"} <= triggers)
        tables = {r["name"] for r in s.c.db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"handoff_packages", "handoff_receipt_details", "handoff_receipts"} <= tables)
        s.assert_books_sound(self)


if __name__ == "__main__":
    unittest.main()
