"""Structured estimates: units, measurement basis, contingency, price book, scope and supersession.

Every test builds its own synthetic workspace.  Cost codes, price books and
parties are original placeholders.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import StaleApprovalError
from apps.cipher.core.db import SCHEMA_CATALOG, WriteAuthorityError
from apps.cipher.core.ids import hash_json
from apps.cipher.domain.commitments import CommitmentError
from apps.cipher.domain.estimates import (
    LIFECYCLE_SCHEMA_NAME, MEASURED_UNITS, NO_REPLACE_SCHEMA_NAME, STRUCTURE_SCHEMA_NAME, UNITS, EstimateError, EstimateStaleError,
    Estimates,
)
from apps.cipher.service import Cipher, RoleNotAuthorised

ENTITY = "S&A Solutions LLC (synthetic)"
BASIS = "synthetic drawing A rev 1 at 1:50, scale verified against the bar scale"
PB1 = "PB-SYN-2026.1"
PB2 = "PB-SYN-2026.2"
LUMP = [{"description": "Pump station, complete", "quantity": "1", "unit": "LS", "unit_price": "100000"}]
ESTIMATE_SCHEMA_NAMES = (STRUCTURE_SCHEMA_NAME, LIFECYCLE_SCHEMA_NAME, NO_REPLACE_SCHEMA_NAME)
LINE_COLUMNS = "(id, estimate_id, line_no, description, quantity, unit, unit_price, amount)"


class Base(unittest.TestCase):
    # a row written around the API: draft, no lines, no estimate.created audit entry
    RAW_INSERT = ("INSERT INTO estimates (id, project_id, document_revision_id, revision, supersedes, status, total, content_hash, created_at, approval_id) "
                  "VALUES (?,?,?,?,?,?,'1.00','h','t',?)")

    def setUp(self):
        self.c = Cipher()
        self.project = self.c.create_project(name="Synthetic cofferdam and pump station", entity=ENTITY, budget="250000")
        self.pid = self.project["id"]
        self.doc = self.c.evidence.register_document(project_id=self.pid, kind="drawing", title="Synthetic drawing A", actor="estimator")
        self.rev = self.c.evidence.add_revision(document_id=self.doc["id"], content=b"synthetic drawing A rev 1", actor="estimator")

    def create(self, lines=None, supersedes=None, **kw):
        return self.c.estimates.create(self.pid, self.rev["id"], lines or LUMP, "estimator", supersedes, **kw)

    def request(self, estimate_id, role="estimator"):
        return self.c.request_approval("estimate.approve", estimate_id, actor_role=role, requested_by=role)

    def granted(self, estimate_id):
        ap = self.request(estimate_id)
        self.c.approve(ap["id"], approver="owner")
        return ap

    def count(self):
        return self.c.db.scalar("SELECT COUNT(*) FROM estimates")

    def audit_actions(self, action, entity_id=None):
        return [e for e in self.c.audit.entries(entity_type="estimate", entity_id=entity_id) if e["action"] == action]

    def assertBooksIntact(self):
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def stored(self, estimate_id):
        return self.c.db.one("SELECT * FROM estimates WHERE id=?", (estimate_id,))

    @staticmethod
    def copy_sql(verb, row, **overrides):
        """``<verb> INTO estimates`` re-using a stored row's id, with some columns changed."""
        data = {**row, **overrides}
        cols = list(data)
        return f"{verb} INTO estimates ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(data[k] for k in cols)


class OldStyleCallTests(Base):
    def test_old_style_call_keeps_totals_units_and_approval_flow(self):
        est = self.c.estimates.create(project_id=self.pid, document_revision_id=self.rev["id"], lines=[
            {"description": "Pump station", "quantity": "1", "unit": "LS", "unit_price": "40000"},
            {"description": "Valve assembly", "quantity": "3", "unit": "ea", "unit_price": "1250.505"},  # price quantised half-up, as before
            {"description": "Flow meter", "quantity": "2", "unit_price": "800"},  # no unit: each
        ], actor="estimator")
        self.assertEqual((est["subtotal"], est["contingency"], est["total"]), ("45351.53", "0.00", "45351.53"))
        self.assertEqual([(ln["unit"], ln["quantity"], ln["unit_price"], ln["amount"]) for ln in est["lines"]],
                         [("LS", "1", "40000.00", "40000.00"), ("EA", "3", "1250.51", "3751.53"), ("EA", "2", "800.00", "1600.00")])
        self.assertEqual((est["contingency_rate"], est["price_book_ref"], est["inclusions"], est["exclusions"], est["measurement_basis"]),
                         ("0.000000", None, [], [], None))
        self.assertEqual((est["status"], est["revision"], est["supersedes"], est["supersession"], est["stale"], est["content_verified"]),
                         ("draft", 1, None, None, False, True))
        self.assertEqual((est["superseded_by"], est["stale_reasons"]), (None, []))
        res = self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        self.assertEqual(res.result, {"estimate": est["id"], "status": "approved"})
        est = self.c.estimates.get(est["id"])
        ap = self.c.approvals.get(est["approval_id"])
        self.assertEqual((est["status"], ap["status"]), ("approved", "consumed"))
        self.assertEqual(ap["manifest"]["amounts"], {"subtotal": "45351.53", "contingency": "0.00", "total": "45351.53"})
        self.assertEqual((ap["manifest"]["entity"], ap["manifest"]["currency"]), (ENTITY, "USD"))
        self.assertEqual(self.c.ledger.journals(), [])  # an estimate never posts to the books
        self.assertBooksIntact()

    def test_old_style_measured_unit_with_basis(self):
        est = self.c.estimates.create(project_id=self.pid, document_revision_id=self.rev["id"], lines=[
            {"description": "Sheet pile cofferdam, furnish and drive", "quantity": "1200", "unit": "SF", "unit_price": "50.00"},
            {"description": "Pump station", "quantity": "1", "unit": "LS", "unit_price": "40000.00"},
        ], actor="estimator", measurement_basis=BASIS)
        self.assertEqual(est["total"], "100000.00")
        self.assertEqual([(ln["quantity"], ln["unit"], ln["amount"]) for ln in est["lines"]], [("1200", "SF", "60000.00"), ("1", "LS", "40000.00")])
        self.assertEqual(est["measurement_basis"], BASIS)

    def test_commitment_still_binds_the_estimate_hash(self):
        supplier = self.c.add_party(kind="supplier", name="Synthetic Sheet Pile Subcontractor", destination="ACH-SIM-EST-1")
        self.c.verify_destination(supplier["id"], destination="ACH-SIM-EST-1", verified_by="bank-detail-maintainer")
        est = self.create(price_book_ref=PB1, exclusions=["Rock excavation"], contingency_rate="0.05")
        self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        cmt = self.c.commitments.create(project_id=self.pid, supplier_id=supplier["id"], title="Synthetic subcontract",
                                        sov_lines=[{"description": "Pump station", "amount": "100000", "cost_code": "XX 10 00"}],
                                        estimate_id=est["id"], actor="pm")
        ap = self.c.request_approval("commitment.execute", cmt["id"], actor_role="pm", requested_by="pm")
        self.assertEqual(ap["manifest"]["bindings"]["estimate_hash"], est["content_hash"])
        self.assertEqual(self.c.commitments.get(cmt["id"])["estimate"]["total"], "105000.00")


class ContingencyTests(Base):
    def test_totals_with_contingency(self):
        est = self.create(contingency_rate="0.075")
        self.assertEqual((est["subtotal"], est["contingency_rate"], est["contingency"], est["total"]),
                         ("100000.00", "0.075000", "7500.00", "107500.00"))
        audit = self.audit_actions("estimate.created", est["id"])[0]
        payload = json.loads(audit["payload_json"])
        self.assertEqual((payload["subtotal"], payload["contingency"], payload["total"]), ("100000.00", "7500.00", "107500.00"))

    def test_contingency_rounds_half_up_to_cents(self):
        est = self.create(lines=[{"description": "Small item", "quantity": "1", "unit": "LS", "unit_price": "10.10"}], contingency_rate="0.05")
        self.assertEqual((est["subtotal"], est["contingency"], est["total"]), ("10.10", "0.51", "10.61"))  # 0.505 -> 0.51
        est = self.create(lines=[{"description": "Odd item", "quantity": "1", "unit": "LS", "unit_price": "1234.57"}], contingency_rate=Decimal("0.033333"))
        self.assertEqual((est["contingency"], est["total"]), ("41.15", "1275.72"))

    def test_rate_bounds_and_types(self):
        one_k = [{"description": "Item", "quantity": "1", "unit": "LS", "unit_price": "1000"}]
        self.assertEqual(self.create(lines=one_k, contingency_rate="0.5")["total"], "1500.00")
        self.assertEqual(self.create(lines=one_k, contingency_rate=Decimal("0.25"))["total"], "1250.00")
        self.assertEqual(self.create(lines=one_k, contingency_rate=0)["contingency_rate"], "0.000000")
        before = self.count()
        for bad in ("0.500001", "0.51", "-0.01", "0.1234567", 0.1, True, "abc", "NaN", "Infinity", "", [], "1e40",
                    Decimal("NaN"), Decimal("Infinity"), 1):
            with self.subTest(rate=bad), self.assertRaises(EstimateError):
                self.create(lines=one_k, contingency_rate=bad)
        # a ratio is not money: currency signs, separators, percent signs and exponents are refused, not stripped
        for bad in ("$0.10", "0.0,5", "0,05", "5%", "1e-1", "0.1 0", ".", "+", "0x0.1", "٠.١"):
            with self.subTest(rate=bad), self.assertRaisesRegex(EstimateError, "plain decimal"):
                self.create(lines=one_k, contingency_rate=bad)
        self.assertEqual(self.count(), before)
        self.assertEqual(len(self.audit_actions("estimate.created")), before)
        self.assertEqual(self.create(lines=one_k, contingency_rate=" 0.20 ")["total"], "1200.00")  # surrounding blanks are fine

    def test_manifest_binds_amounts_rate_entity_and_currency(self):
        est = self.create(contingency_rate="0.10")
        m = self.request(est["id"])["manifest"]
        self.assertEqual(m["amounts"], {"subtotal": "100000.00", "contingency": "10000.00", "total": "110000.00"})
        self.assertEqual(m["bindings"]["contingency_rate"], "0.100000")
        self.assertEqual((m["entity"], m["currency"], m["subject"]), (ENTITY, "USD", {"type": "estimate", "id": est["id"]}))


class UnitTests(Base):
    def test_registry_is_case_insensitive_and_stored_upper_case(self):
        units = ["ls", " Ea ", "hr", "Day", "gal", "LB", "mo", "ton"]
        est = self.create(lines=[{"description": f"Item {i}", "quantity": "2", "unit": u, "unit_price": "10"} for i, u in enumerate(units, 1)])
        self.assertEqual([ln["unit"] for ln in est["lines"]], ["LS", "EA", "HR", "DAY", "GAL", "LB", "MO", "TON"])
        self.assertEqual(est["total"], "160.00")
        self.assertIsNone(est["measurement_basis"])  # none of these is a measured unit

    def test_unknown_units_are_rejected(self):
        for bad in ("FT", "M2", "each", "", "   ", "L S", 5, ["LS"]):
            with self.subTest(unit=bad), self.assertRaisesRegex(EstimateError, "unit"):
                self.create(lines=[{"description": "Item", "quantity": "1", "unit": bad, "unit_price": "10"}], measurement_basis=BASIS)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.audit_actions("estimate.created"), [])

    def test_registry_listing(self):
        self.assertEqual(set(UNITS), {"LS", "EA", "LF", "SF", "SY", "CY", "TON", "HR", "DAY", "GAL", "LB", "MO"})
        self.assertEqual(MEASURED_UNITS, {"LF", "SF", "SY", "CY"})
        self.assertEqual({u["unit"] for u in Estimates.units() if u["measured"]}, {"LF", "SF", "SY", "CY"})

    def test_measured_units_require_a_measurement_basis(self):
        for unit in ("LF", "sf", "SY", "cy"):
            line = [{"description": f"Measured item in {unit}", "quantity": "40", "unit": unit, "unit_price": "12.50"}]
            with self.subTest(unit=unit):
                with self.assertRaisesRegex(EstimateError, "unit/scale"):
                    self.create(lines=line)
                with self.assertRaisesRegex(EstimateError, "unit/scale"):
                    self.create(lines=line, measurement_basis="   ")
                self.assertEqual(self.count(), 0)
        est = self.create(lines=[{"description": "Cofferdam wall", "quantity": "1200", "unit": "sf", "unit_price": "50"},
                                 {"description": "Haul-off", "quantity": "30", "unit": "TON", "unit_price": "20"}],
                          measurement_basis=f"  {BASIS}  ")
        self.assertEqual((est["measurement_basis"], est["total"], est["lines"][0]["unit"]), (BASIS, "60600.00", "SF"))
        m = self.request(est["id"])["manifest"]
        self.assertEqual((m["bindings"]["measurement_basis"], m["bindings"]["units"]), (BASIS, ["SF", "TON"]))


class BindingTests(Base):
    BASE = dict(price_book_ref=PB1, inclusions=["Dewatering"], exclusions=["Rock excavation"], contingency_rate="0.05", measurement_basis=BASIS)

    def test_content_hash_binds_every_structured_fact(self):
        # parallel estimates of the same scope from the same drawing must carry each other's
        # exclusions (ParallelEstimateTests), so the variant that adds one comes last
        variants = {
            "base": {},
            "price_book": {"price_book_ref": PB2},
            "inclusions": {"inclusions": ["Dewatering", "Traffic control"]},
            "contingency": {"contingency_rate": "0.06"},
            "basis": {"measurement_basis": BASIS + " (re-measured)"},
            "exclusions": {"exclusions": ["Rock excavation", "Electrical service"]},
        }
        hashes = {name: self.create(**{**self.BASE, **change})["content_hash"] for name, change in variants.items()}
        self.assertEqual(len(set(hashes.values())), len(variants), hashes)

    def test_manifest_binds_scope_price_book_and_basis(self):
        est = self.create(**self.BASE)
        m = self.request(est["id"])["manifest"]
        b = m["bindings"]
        self.assertEqual((b["estimate_hash"], b["project_id"], b["price_book_ref"], b["inclusions"], b["exclusions"]),
                         (est["content_hash"], self.pid, PB1, ["Dewatering"], ["Rock excavation"]))
        self.assertEqual((b["supersedes"], b["price_book_previous"], b["price_book_changed"], b["removed_exclusions"]), (None, None, False, []))
        self.assertEqual((b["supersession_baseline"], b["unrecorded_revisions"], b["overlapping_estimates"]), (None, [], []))
        self.assertEqual(m["amounts"]["total"], "105000.00")

    def test_identical_estimate_is_rejected_as_duplicate(self):
        first = self.create(**self.BASE)
        with self.assertRaisesRegex(EstimateError, "duplicate"):
            self.create(**self.BASE)
        with self.assertRaisesRegex(EstimateError, "duplicate"):  # whitespace-only differences normalise to the same content
            self.create(**{**self.BASE, "exclusions": ["  Rock   excavation "]})
        self.assertEqual(self.count(), 1)
        self.c.approve_and_execute("estimate.approve", first["id"], actor_role="estimator", actor="estimator")
        with self.assertRaisesRegex(EstimateError, "duplicate"):  # an approved twin is a duplicate too
            self.create(**self.BASE)


class SupersedeTests(Base):
    EXCL = ["Rock excavation", "Electrical service"]

    def v1(self, **kw):
        return self.create(**{"price_book_ref": PB1, "inclusions": ["Dewatering"], "exclusions": self.EXCL, **kw})

    def test_dropping_an_exclusion_needs_removed_exclusions_and_stales_the_open_approval(self):
        v1 = self.v1()
        ap = self.granted(v1["id"])
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB1, inclusions=["Dewatering"], exclusions=["Electrical service"],
                         removed_exclusions=["rock  EXCAVATION"])
        self.assertEqual((v2["revision"], v2["supersedes"], v2["status"]), (2, v1["id"], "draft"))
        self.assertNotEqual(v2["content_hash"], v1["content_hash"])
        old = self.c.estimates.get(v1["id"])
        self.assertEqual((old["status"], old["stale"], old["superseded_by"], old["stale_reasons"]),
                         ("superseded", True, v2["id"], [f"superseded by estimate {v2['id']}"]))
        self.assertEqual((v2["stale"], v2["superseded_by"], v2["stale_reasons"]), (False, None, []))
        ap_now = self.c.approvals.get(ap["id"])
        self.assertEqual(ap_now["status"], "invalidated")
        self.assertIn(v2["id"], ap_now["invalidated_reason"])
        with self.assertRaisesRegex(EstimateError, "superseded"):
            self.c.execute(ap["id"], actor="estimator")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertIsNone(self.c.estimates.get(v1["id"])["approval_id"])
        self.assertEqual(v2["supersession"]["removed_exclusions"], ["Rock excavation"])
        self.assertFalse(v2["supersession"]["price_book_changed"])
        created = json.loads(self.audit_actions("estimate.created", v2["id"])[0]["payload_json"])
        self.assertEqual((created["removed_exclusions"], created["price_book"]), (["Rock excavation"], {"previous": PB1, "current": PB1, "changed": False}))
        superseded = json.loads(self.audit_actions("estimate.superseded", v1["id"])[0]["payload_json"])
        self.assertEqual((superseded["superseded_by"], superseded["removed_exclusions"]), (v2["id"], ["Rock excavation"]))
        m = self.request(v2["id"])["manifest"]
        self.assertEqual((m["bindings"]["supersedes"], m["bindings"]["superseded_estimate_hash"], m["bindings"]["removed_exclusions"], m["bindings"]["exclusions"]),
                         (v1["id"], v1["content_hash"], ["Rock excavation"], ["Electrical service"]))
        self.assertEqual((m["bindings"]["supersession_baseline"], m["bindings"]["unrecorded_revisions"]),
                         ({"estimate_id": v1["id"], "content_hash": v1["content_hash"], "record_intact": True}, []))
        self.c.approve_and_execute("estimate.approve", v2["id"], actor_role="estimator", actor="estimator")
        self.assertEqual(self.c.estimates.get(v2["id"])["status"], "approved")
        self.assertBooksIntact()

    def test_price_book_must_be_kept_or_explicitly_changed(self):
        v1 = self.v1()
        ap = self.granted(v1["id"])
        with self.assertRaisesRegex(EstimateError, "price book"):
            self.create(supersedes=v1["id"], inclusions=["Dewatering"], exclusions=self.EXCL)
        self.assertEqual((self.c.estimates.get(v1["id"])["status"], self.c.approvals.get(ap["id"])["status"], self.count()), ("draft", "granted", 1))
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB2, inclusions=["Dewatering"], exclusions=self.EXCL)
        self.assertNotEqual(v2["content_hash"], v1["content_hash"])
        self.assertEqual((v2["supersession"]["price_book_previous"], v2["supersession"]["price_book_changed"], v2["price_book_ref"]), (PB1, True, PB2))
        created = json.loads(self.audit_actions("estimate.created", v2["id"])[0]["payload_json"])
        self.assertEqual(created["price_book"], {"previous": PB1, "current": PB2, "changed": True})
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(EstimateError):
            self.c.execute(ap["id"], actor="estimator")
        b = self.request(v2["id"])["manifest"]["bindings"]
        self.assertEqual((b["price_book_ref"], b["price_book_previous"], b["price_book_changed"]), (PB2, PB1, True))
        # keeping the (new) edition is recorded as unchanged
        v3 = self.create(supersedes=v2["id"], price_book_ref=PB2, inclusions=["Dewatering"], exclusions=self.EXCL, contingency_rate="0.05")
        self.assertEqual((v3["revision"], v3["supersession"]["price_book_changed"], v3["total"]), (3, False, "105000.00"))
        # an estimate without a price book may gain one; the change is recorded
        plain = self.create(lines=[{"description": "Spare parts", "quantity": "1", "unit": "LS", "unit_price": "500"}])
        named = self.create(lines=[{"description": "Spare parts", "quantity": "1", "unit": "LS", "unit_price": "500"}], supersedes=plain["id"], price_book_ref=PB1)
        self.assertEqual((named["supersession"]["price_book_previous"], named["supersession"]["price_book_changed"]), (None, True))
        self.assertBooksIntact()

    def test_exclusions_cannot_be_dropped_silently(self):
        v1 = self.v1()
        ap = self.granted(v1["id"])
        attempts = [
            ({"exclusions": ["Electrical service"]}, "Rock excavation"),
            ({}, "Electrical service"),
            ({"exclusions": ["Electrical service"], "removed_exclusions": ["Traffic control"]}, "not an exclusion"),
            ({"exclusions": self.EXCL, "removed_exclusions": ["Rock excavation"]}, "still excluded"),
        ]
        for kwargs, message in attempts:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(EstimateError, message):
                self.create(supersedes=v1["id"], price_book_ref=PB1, inclusions=["Dewatering"], **kwargs)
        self.assertEqual((self.c.estimates.get(v1["id"])["status"], self.c.approvals.get(ap["id"])["status"], self.count()), ("draft", "granted", 1))
        self.assertEqual(self.audit_actions("estimate.superseded"), [])
        # the same exclusions written differently are kept, not dropped; a new one is recorded as added
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB1, inclusions=["Dewatering"],
                         exclusions=["  rock EXCAVATION ", "electrical service", "Traffic control"])
        self.assertEqual((v2["supersession"]["removed_exclusions"], v2["supersession"]["added_exclusions"]), ([], ["Traffic control"]))

    def test_supersession_scope_and_duplicate_rules(self):
        with self.assertRaisesRegex(EstimateError, "removed_exclusions"):
            self.create(removed_exclusions=["Rock excavation"])
        with self.assertRaisesRegex(EstimateError, "unknown estimate"):
            self.create(supersedes="est_missing")
        other = self.c.create_project(name="Other synthetic project", entity=ENTITY, budget="1000")
        odoc = self.c.evidence.register_document(project_id=other["id"], kind="drawing", title="Other drawing", actor="estimator")
        orev = self.c.evidence.add_revision(document_id=odoc["id"], content=b"other drawing rev 1", actor="estimator")
        foreign = self.c.estimates.create(other["id"], orev["id"], LUMP, "estimator")
        with self.assertRaisesRegex(EstimateError, "another project"):
            self.create(supersedes=foreign["id"])
        v1 = self.v1()
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB1, exclusions=self.EXCL, contingency_rate="0.02")
        with self.assertRaisesRegex(EstimateError, "already superseded"):  # no fork of the revision chain
            self.create(supersedes=v1["id"], price_book_ref=PB1, exclusions=self.EXCL, contingency_rate="0.03")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM estimates WHERE supersedes=?", (v1["id"],)), 1)
        # an approved estimate may be superseded; its approval history is kept
        self.c.approve_and_execute("estimate.approve", v2["id"], actor_role="estimator", actor="estimator")
        approved = self.c.estimates.get(v2["id"])
        v3 = self.create(supersedes=v2["id"], price_book_ref=PB1, exclusions=self.EXCL, contingency_rate="0.04")
        prior = self.c.estimates.get(v2["id"])
        self.assertEqual((prior["status"], prior["approval_id"], v3["revision"]), ("superseded", approved["approval_id"], 3))
        self.assertEqual(json.loads(self.audit_actions("estimate.superseded", v2["id"])[0]["payload_json"])["previous_status"], "approved")
        self.assertBooksIntact()

    def test_raw_successor_cannot_launder_exclusions_or_the_price_book(self):
        v1 = self.v1()
        ap = self.granted(v1["id"])
        # a successor written with plain SQL, without the exclusions or the price book; the schema lets it supersede v1 ...
        self.c.db.execute(self.RAW_INSERT, ("est_raw_v2", self.pid, self.rev["id"], 2, v1["id"], "draft", None))
        self.assertEqual(self.c.estimates.get(v1["id"])["status"], "superseded")
        raw = self.c.estimates.get("est_raw_v2")
        self.assertEqual((raw["stale"], raw["creation_recorded"]), (True, False))
        self.assertIn("not created through Cipher (no matching estimate.created audit entry)", raw["stale_reasons"])
        # ... but it is measured against v1's recorded scope, so what it dropped shows
        sup = raw["supersession"]
        self.assertEqual((sup["baseline"]["estimate_id"], sup["removed_exclusions"], sup["price_book_previous"], sup["price_book_changed"]),
                         (v1["id"], self.EXCL, PB1, True))
        # the approval granted on v1 never executes, and executing it invalidates it instead of leaving it granted
        with self.assertRaisesRegex(EstimateError, "superseded"):
            self.c.execute(ap["id"], actor="estimator")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        # a successor of the raw row is checked against v1, not against the raw row
        for kwargs, message in (
            ({}, "price book 'PB-SYN-2026.1'"),
            ({"price_book_ref": PB1}, "drop exclusions \\['Rock excavation', 'Electrical service'\\]"),
            ({"price_book_ref": PB1, "exclusions": ["Electrical service"]}, "Rock excavation"),
            ({"price_book_ref": PB1, "removed_exclusions": ["Rock excavation"]}, "Electrical service"),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(EstimateError, message):
                self.create(supersedes="est_raw_v2", inclusions=["Dewatering"], **kwargs)
        self.assertEqual(self.count(), 2)
        v3 = self.create(supersedes="est_raw_v2", price_book_ref=PB1, inclusions=["Dewatering"], exclusions=["Electrical service"],
                         removed_exclusions=["Rock excavation"])
        sup = v3["supersession"]
        self.assertEqual((v3["revision"], sup["removed_exclusions"], sup["baseline"]["estimate_id"], sup["unrecorded_revisions"], sup["price_book_changed"]),
                         (3, ["Rock excavation"], v1["id"], ["est_raw_v2"], False))
        created = json.loads(self.audit_actions("estimate.created", v3["id"])[0]["payload_json"])
        self.assertEqual((created["compared_with"], created["unrecorded_revisions"], created["removed_exclusions"], created["price_book"]),
                         (v1["id"], ["est_raw_v2"], ["Rock excavation"], {"previous": PB1, "current": PB1, "changed": False}))
        superseded = json.loads(self.audit_actions("estimate.superseded", "est_raw_v2")[0]["payload_json"])
        self.assertEqual((superseded["superseded_by"], superseded["compared_with"]), (v3["id"], v1["id"]))
        b = self.request(v3["id"])["manifest"]["bindings"]
        self.assertEqual((b["supersedes"], b["supersession_baseline"]["estimate_id"], b["unrecorded_revisions"], b["removed_exclusions"], b["price_book_previous"]),
                         ("est_raw_v2", v1["id"], ["est_raw_v2"], ["Rock excavation"], PB1))
        self.c.approve_and_execute("estimate.approve", v3["id"], actor_role="estimator", actor="estimator")
        self.assertEqual(self.c.estimates.get(v3["id"])["status"], "approved")
        self.assertBooksIntact()

    def test_rewritten_predecessor_is_compared_by_what_it_was_created_with(self):
        v1 = self.v1()
        self.c.db.execute("DROP TRIGGER estimates_content_immutable")  # a write that bypasses the guards
        self.c.db.execute("UPDATE estimates SET exclusions_json='[]', price_book_ref=NULL WHERE id=?", (v1["id"],))
        tampered = self.c.estimates.get(v1["id"])
        self.assertEqual((tampered["content_verified"], tampered["stale"], tampered["exclusions"], tampered["price_book_ref"]), (False, True, [], None))
        with self.assertRaisesRegex(EstimateError, "price book"):
            self.create(supersedes=v1["id"], inclusions=["Dewatering"])
        with self.assertRaisesRegex(EstimateError, "Rock excavation"):
            self.create(supersedes=v1["id"], price_book_ref=PB1, inclusions=["Dewatering"], exclusions=["Electrical service"])
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB1, inclusions=["Dewatering"], exclusions=["Electrical service"],
                         removed_exclusions=["Rock excavation"])
        sup = v2["supersession"]
        self.assertEqual((sup["removed_exclusions"], sup["price_book_previous"], sup["price_book_changed"], sup["baseline"]),
                         (["Rock excavation"], PB1, False, {"estimate_id": v1["id"], "content_hash": v1["content_hash"], "record_intact": False}))
        self.assertEqual(self.c.estimates.get(v1["id"])["status"], "superseded")

    def test_a_chain_nobody_created_through_cipher_cannot_be_superseded(self):
        self.c.db.execute(self.RAW_INSERT, ("est_raw_root", self.pid, self.rev["id"], 1, None, "draft", None))
        with self.assertRaisesRegex(EstimateError, "not created through Cipher"):
            self.create(supersedes="est_raw_root")
        self.c.db.execute(self.RAW_INSERT, ("est_raw_next", self.pid, self.rev["id"], 2, "est_raw_root", "draft", None))
        with self.assertRaisesRegex(EstimateError, "not created through Cipher"):
            self.create(supersedes="est_raw_next")
        self.assertEqual((self.count(), self.audit_actions("estimate.created")), (2, []))
        # a new estimate is the way forward; the unrecorded chain binds nothing on it but is flagged to the approver
        est = self.create()
        overlaps = self.request(est["id"])["manifest"]["bindings"]["overlapping_estimates"]
        self.assertEqual([(o["estimate_id"], o["same_document"], o["shared_lines"], o["scope_recorded_by"]) for o in overlaps],
                         [("est_raw_next", True, [], None)])


class ApprovalControlTests(Base):
    def test_only_a_draft_can_be_put_up_for_approval(self):
        est = self.create()
        self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        with self.assertRaisesRegex(EstimateError, "approved"):
            self.request(est["id"])
        nxt = self.create(supersedes=est["id"], contingency_rate="0.01")
        with self.assertRaisesRegex(EstimateError, "superseded"):
            self.request(est["id"])
        self.assertEqual(self.c.ricky.propose("estimate.approve", actor_role="estimator", context={"estimate_id": est["id"]})["decision"], "abstained")
        proposal = self.c.ricky.propose("estimate.approve", actor_role="estimator", context={"estimate_id": nxt["id"]})
        self.assertEqual((proposal["decision"], proposal["manifest"]["amounts"]["contingency"]), ("proposed", "1000.00"))

    def test_second_open_approval_is_invalidated_when_the_first_executes(self):
        est = self.create()
        ap1, ap2 = self.granted(est["id"]), self.granted(est["id"])
        self.c.execute(ap1["id"], actor="estimator")
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "invalidated")
        with self.assertRaises(EstimateError):
            self.c.execute(ap2["id"], actor="estimator")
        est = self.c.estimates.get(est["id"])
        self.assertEqual((est["status"], est["approval_id"]), ("approved", ap1["id"]))
        self.assertEqual(len(self.audit_actions("estimate.approved")), 1)

    def test_roles(self):
        est = self.create()
        for role in ("pm", "viewer", "treasury"):
            with self.subTest(role=role), self.assertRaises(RoleNotAuthorised):
                self.request(est["id"], role=role)
        ap = self.request(est["id"])
        with self.assertRaises(RoleNotAuthorised):
            self.c.approve(ap["id"], approver="pm", approver_role="pm")
        self.c.approve(ap["id"], approver="estimator", approver_role="estimator")
        self.assertEqual(self.c.execute(ap["id"], actor="estimator").result["status"], "approved")

    def test_new_document_revision_after_grant_makes_the_approval_stale(self):
        est = self.create()
        ap = self.granted(est["id"])
        self.c.evidence.add_revision(document_id=self.doc["id"], content=b"synthetic drawing A rev 2", actor="engineer")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="estimator")
        ap_now = self.c.approvals.get(ap["id"])
        self.assertEqual(ap_now["status"], "invalidated")
        self.assertIn("priced from a superseded document revision", ap_now["invalidated_reason"])
        est = self.c.estimates.get(est["id"])
        self.assertEqual((est["status"], est["stale"]), ("draft", True))

    def test_request_after_a_document_revision_is_refused(self):
        est = self.create()
        self.c.evidence.add_revision(document_id=self.doc["id"], content=b"synthetic drawing A rev 2", actor="engineer")
        before = len(self.c.approvals.list())
        with self.assertRaisesRegex(EstimateError, "priced from a superseded document revision") as caught:
            self.request(est["id"])
        self.assertIsInstance(caught.exception, EstimateStaleError)
        self.assertIsInstance(caught.exception, StaleApprovalError)  # so an approval granted earlier is invalidated on execute
        self.assertEqual(len(self.c.approvals.list()), before)  # refused at request time: no approval that can never execute
        self.assertEqual(self.c.ricky.propose("estimate.approve", actor_role="estimator", context={"estimate_id": est["id"]})["decision"], "abstained")
        with self.assertRaisesRegex(EstimateError, "superseded document revision"):
            self.c.estimates.approve(est["id"], approval_id="apr_bogus", actor="estimator")
        self.assertEqual(self.c.estimates.get(est["id"])["status"], "draft")

    def test_direct_approve_requires_a_consumed_matching_approval(self):
        est = self.create()
        other = self.create(lines=[{"description": "Other", "quantity": "1", "unit": "LS", "unit_price": "5"}])
        pending = self.request(est["id"])
        self.c.approve_and_execute("estimate.approve", other["id"], actor_role="estimator", actor="estimator")
        other_ap = self.c.estimates.get(other["id"])["approval_id"]
        for approval_id in ("apr_bogus", pending["id"], other_ap):
            with self.subTest(approval_id=approval_id), self.assertRaisesRegex(EstimateError, "not a consumed"):
                self.c.estimates.approve(est["id"], approval_id=approval_id, actor="estimator")
        self.assertEqual(self.c.estimates.get(est["id"])["status"], "draft")

    def test_restored_copy_cannot_create_estimates(self):
        d = tempfile.mkdtemp()
        live = Cipher(os.path.join(d, "live.sqlite"))
        self.addCleanup(live.db.close)
        project = live.create_project(name="Synthetic restore project", entity=ENTITY, budget="1000")
        doc = live.evidence.register_document(project_id=project["id"], kind="drawing", title="Synthetic drawing", actor="estimator")
        rev = live.evidence.add_revision(document_id=doc["id"], content=b"synthetic drawing rev 1", actor="estimator")
        restored = Cipher.open_restored(live.snapshot(os.path.join(d, "backup.sqlite")))
        self.addCleanup(restored.db.close)
        with self.assertRaises(WriteAuthorityError):
            restored.estimates.create(project["id"], rev["id"], LUMP, "estimator")
        self.assertEqual(restored.db.scalar("SELECT COUNT(*) FROM estimates"), 0)


class IntegrityTests(Base):
    def test_content_lines_and_lifecycle_are_guarded_by_the_schema(self):
        est = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        db = self.c.db
        for sql in (
            "UPDATE estimates SET exclusions_json='[]' WHERE id=?",
            "UPDATE estimates SET price_book_ref='PB-SYN-OTHER' WHERE id=?",
            "UPDATE estimates SET contingency_rate='0.100000' WHERE id=?",
            "UPDATE estimates SET total='1.00' WHERE id=?",
            "UPDATE estimates SET measurement_basis='forged' WHERE id=?",
            "UPDATE estimate_lines SET amount='1.00' WHERE estimate_id=?",
            "DELETE FROM estimate_lines WHERE estimate_id=?",
            "DELETE FROM estimates WHERE id=?",
            "UPDATE estimates SET status='approved' WHERE id=?",  # no approval reference
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql, (est["id"],))
        self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        for sql in (
            "UPDATE estimates SET status='draft' WHERE id=?",
            "UPDATE estimates SET approval_id=NULL WHERE id=?",
            "INSERT INTO estimate_lines (id, estimate_id, line_no, description, quantity, unit, unit_price, amount) VALUES ('eln_forged', ?, 2, 'forged', '1', 'LS', '1.00', '1.00')",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql, (est["id"],))
        nxt = self.create(supersedes=est["id"], price_book_ref=PB1, exclusions=["Rock excavation"], contingency_rate="0.01")
        with self.assertRaises(sqlite3.DatabaseError):  # a second successor
            db.execute("""INSERT INTO estimates (id, project_id, document_revision_id, revision, supersedes, status, total, content_hash, created_at)
                          VALUES ('est_fork', ?, ?, 2, ?, 'draft', '1.00', 'h', 't')""", (self.pid, self.rev["id"], est["id"]))
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE estimates SET status='draft' WHERE id=?", (est["id"],))
        self.assertTrue(self.c.estimates.get(nxt["id"])["content_verified"])
        self.assertBooksIntact()

    def test_tampering_is_detected_when_the_guards_are_bypassed(self):
        est = self.create(price_book_ref=PB1, contingency_rate="0.05")
        ap = self.granted(est["id"])
        self.assertTrue(est["content_verified"])
        self.c.db.execute("DROP TRIGGER estimates_content_immutable")
        self.c.db.execute("UPDATE estimates SET exclusions_json='[\"forged exclusion\"]' WHERE id=?", (est["id"],))
        tampered = self.c.estimates.get(est["id"])
        self.assertEqual((tampered["content_verified"], tampered["stale"]), (False, True))
        self.assertIn("its stored content no longer matches its content hash", tampered["stale_reasons"])
        with self.assertRaisesRegex(EstimateError, "content hash"):
            self.c.execute(ap["id"], actor="estimator")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")  # granted against other content: it is spent
        with self.assertRaisesRegex(EstimateError, "content hash"):
            self.request(est["id"])
        self.assertEqual(self.c.estimates.get(est["id"])["status"], "draft")

        other = self.create(lines=[{"description": "Other", "quantity": "2", "unit": "EA", "unit_price": "5"}])
        self.c.db.execute("DROP TRIGGER estimate_lines_no_update")
        self.c.db.execute("UPDATE estimate_lines SET quantity='3', amount='15.00' WHERE estimate_id=?", (other["id"],))
        self.assertFalse(self.c.estimates.get(other["id"])["content_verified"])
        with self.assertRaisesRegex(EstimateError, "content hash"):
            self.request(other["id"])

    def test_replace_ignore_and_upsert_cannot_rewrite_or_revive_an_approved_estimate(self):
        est = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        approved = self.c.estimates.get(est["id"])
        row = self.stored(est["id"])
        insert_sql, insert_params = self.copy_sql("INSERT", row, status="draft", approval_id=None)
        attempts = {
            # approved -> draft, so it could be approved a second time
            "INSERT OR REPLACE": self.copy_sql("INSERT OR REPLACE", row, status="draft", approval_id=None),
            # same content hash, other scope, price book and total under an approval that binds only the hash
            "REPLACE": self.copy_sql("REPLACE", row, status="draft", approval_id=None, exclusions_json="[]", price_book_ref="PB-SYN-CHEAP", total="1.00"),
            "INSERT OR IGNORE": self.copy_sql("INSERT OR IGNORE", row, status="draft", approval_id=None),
            "INSERT OR FAIL": self.copy_sql("INSERT OR FAIL", row, status="draft", approval_id=None),
            "INSERT": (insert_sql, insert_params),
            "upsert": (insert_sql + " ON CONFLICT(id) DO UPDATE SET exclusions_json='[]'", insert_params),
            "upsert nothing": (insert_sql + " ON CONFLICT DO NOTHING", insert_params),
        }
        for name, (sql, params) in attempts.items():
            with self.subTest(statement=name), self.assertRaisesRegex(sqlite3.IntegrityError, "never replaced"):
                self.c.db.execute(sql, params)
        now = self.c.estimates.get(est["id"])
        self.assertEqual((now["status"], now["approval_id"], now["exclusions"], now["price_book_ref"], now["total"], now["content_verified"], now["stale"]),
                         ("approved", approved["approval_id"], ["Rock excavation"], PB1, "100000.00", True, False))
        self.assertEqual(len(now["lines"]), 1)
        with self.assertRaisesRegex(EstimateError, "approved"):  # it cannot be put up for approval a second time
            self.request(est["id"])
        self.assertEqual((len(self.audit_actions("estimate.approved", est["id"])), self.count()), (1, 1))
        self.assertBooksIntact()

    def test_replace_cannot_revive_a_superseded_estimate(self):
        v1 = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB1, exclusions=["Rock excavation"], contingency_rate="0.01")
        for verb in ("REPLACE", "INSERT OR REPLACE", "INSERT OR IGNORE"):
            sql, params = self.copy_sql(verb, self.stored(v1["id"]), status="draft")
            with self.subTest(verb=verb), self.assertRaisesRegex(sqlite3.IntegrityError, "never replaced"):
                self.c.db.execute(sql, params)
        self.assertEqual(self.c.estimates.get(v1["id"])["status"], "superseded")
        with self.assertRaisesRegex(EstimateError, "superseded"):
            self.request(v1["id"])
        self.assertTrue(self.c.estimates.get(v2["id"])["content_verified"])

    def test_replace_cannot_move_or_rewrite_estimate_lines(self):
        est = self.create(price_book_ref=PB1)
        self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        draft = self.create(lines=[{"description": "Other", "quantity": "1", "unit": "LS", "unit_price": "5"}])
        line = self.c.estimates.get(est["id"])["lines"][0]
        draft_line = self.c.estimates.get(draft["id"])["lines"][0]
        # into the draft, so only the replace guard stands in the way
        for verb, params in (
            ("INSERT OR REPLACE", (line["id"], draft["id"], 2, "moved", "1", "LS", "5.00", "5.00")),  # steal the approved estimate's line
            ("INSERT OR IGNORE", (line["id"], draft["id"], 2, "moved", "1", "LS", "5.00", "5.00")),
            ("REPLACE", (draft_line["id"], draft["id"], 1, "Other", "9", "LS", "5.00", "45.00")),
            ("INSERT", ("eln_second_line_1", draft["id"], 1, "Second line 1", "1", "LS", "5.00", "5.00")),  # a line number it already has
        ):
            with self.subTest(verb=verb, params=params), self.assertRaisesRegex(sqlite3.IntegrityError, "never replaced"):
                self.c.db.execute(f"{verb} INTO estimate_lines {LINE_COLUMNS} VALUES (?,?,?,?,?,?,?,?)", params)
        with self.assertRaises(sqlite3.IntegrityError):  # into the approved estimate: refused either way
            self.c.db.execute(f"REPLACE INTO estimate_lines {LINE_COLUMNS} VALUES (?,?,?,?,?,?,?,?)",
                              (line["id"], est["id"], 1, line["description"], "1", "LS", "1.00", "1.00"))
        for estimate_id, total_ in ((est["id"], "100000.00"), (draft["id"], "5.00")):
            got = self.c.estimates.get(estimate_id)
            self.assertEqual((len(got["lines"]), got["total"], got["content_verified"]), (1, total_, True))

    def test_schema_approves_only_with_a_consumed_approval_for_that_estimate(self):
        est = self.create()
        other = self.create(lines=[{"description": "Other", "quantity": "1", "unit": "LS", "unit_price": "5"}])
        pending = self.request(est["id"])
        granted = self.granted(est["id"])
        self.c.approve_and_execute("estimate.approve", other["id"], actor_role="estimator", actor="estimator")
        other_ap = self.c.estimates.get(other["id"])["approval_id"]
        self.assertEqual(self.c.approvals.get(other_ap)["status"], "consumed")
        for approval_id in (pending["id"], granted["id"], other_ap, "apr_bogus"):  # pending, granted, another estimate's, none
            with self.subTest(approval_id=approval_id), self.assertRaises(sqlite3.IntegrityError):
                self.c.db.execute("UPDATE estimates SET status='approved', approval_id=? WHERE id=?", (approval_id, est["id"]))
        with self.assertRaises(sqlite3.IntegrityError):  # attaching an approval to a draft is no shortcut either
            self.c.db.execute("UPDATE estimates SET approval_id=? WHERE id=?", (other_ap, est["id"]))
        now = self.c.estimates.get(est["id"])
        self.assertEqual((now["status"], now["approval_id"]), ("draft", None))
        # the governed path still works, and an approved estimate cannot be re-pointed at another approval
        self.assertEqual(self.c.execute(granted["id"], actor="estimator").result["status"], "approved")
        self.assertEqual(self.c.estimates.get(est["id"])["approval_id"], granted["id"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE estimates SET approval_id=? WHERE id=?", (other_ap, est["id"]))
        self.assertEqual(self.c.estimates.get(est["id"])["approval_id"], granted["id"])
        self.assertBooksIntact()

    def test_schema_inserts_only_drafts(self):
        est = self.create()
        self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        ap_id = self.c.estimates.get(est["id"])["approval_id"]
        for row in (
            ("est_raw1", self.pid, self.rev["id"], 1, None, "approved", None),
            ("est_raw2", self.pid, self.rev["id"], 1, None, "approved", ap_id),
            ("est_raw3", self.pid, self.rev["id"], 1, None, "superseded", None),
            ("est_raw4", self.pid, self.rev["id"], 1, None, "draft", ap_id),
            ("est_raw5", self.pid, self.rev["id"], 2, None, "draft", None),  # revision 2 of nothing
        ):
            with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                self.c.db.execute(self.RAW_INSERT, row)
        self.assertEqual(self.count(), 1)

    def test_schema_supersedes_only_through_an_existing_successor(self):
        draft = self.create(price_book_ref=PB1)
        approved = self.create(lines=[{"description": "Other", "quantity": "1", "unit": "LS", "unit_price": "5"}])
        self.c.approve_and_execute("estimate.approve", approved["id"], actor_role="estimator", actor="estimator")
        for est in (draft, approved):  # no successor row: refused, whatever the status
            with self.subTest(estimate=est["id"]), self.assertRaises(sqlite3.IntegrityError):
                self.c.db.execute("UPDATE estimates SET status='superseded' WHERE id=?", (est["id"],))
        other = self.c.create_project(name="Other synthetic project", entity=ENTITY, budget="1000")
        for row in (
            ("est_bad1", self.pid, self.rev["id"], 3, draft["id"], "draft", None),     # skips a revision number
            ("est_bad2", other["id"], self.rev["id"], 2, draft["id"], "draft", None),  # follows another project's estimate
            ("est_bad3", self.pid, self.rev["id"], 2, "est_missing", "draft", None),   # follows nothing
        ):
            with self.subTest(row=row), self.assertRaises(sqlite3.IntegrityError):
                self.c.db.execute(self.RAW_INSERT, row)
        self.assertEqual((self.c.estimates.get(draft["id"])["status"], self.c.estimates.get(approved["id"])["status"]), ("draft", "approved"))
        # a successor written around the API supersedes its predecessor in the same statement
        self.c.db.execute(self.RAW_INSERT, ("est_raw_successor", self.pid, self.rev["id"], 2, draft["id"], "draft", None))
        pred = self.c.estimates.get(draft["id"])
        self.assertEqual((pred["status"], pred["superseded_by"], pred["stale"]), ("superseded", "est_raw_successor", True))
        with self.assertRaisesRegex(EstimateError, "superseded"):
            self.request(draft["id"])
        with self.assertRaisesRegex(EstimateError, "already superseded by est_raw_successor"):  # an EstimateError, not a raw IntegrityError
            self.create(supersedes=draft["id"], price_book_ref=PB1, contingency_rate="0.01")
        with self.assertRaisesRegex(EstimateError, "content hash"):  # the raw successor itself can never be approved
            self.request("est_raw_successor")
        with self.assertRaises(sqlite3.IntegrityError):  # and the chain cannot fork
            self.c.db.execute(self.RAW_INSERT, ("est_bad4", self.pid, self.rev["id"], 2, draft["id"], "draft", None))
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_forged_row_with_a_valid_hash_is_never_put_up_for_approval(self):
        real = self.create(price_book_ref=PB1, exclusions=["Rock excavation"], contingency_rate="0.05")
        row = self.c.db.one("SELECT * FROM estimates WHERE id=?", (real["id"],))
        # a copy under a new id re-derives (the content hash does not cover the id) ...
        cols = [k for k in row if k not in ("id", "status", "approval_id")]
        self.c.db.execute(f"INSERT INTO estimates (id, status, {', '.join(cols)}) VALUES ('est_forged', 'draft', {', '.join('?' * len(cols))})",
                          tuple(row[k] for k in cols))
        for ln in real["lines"]:
            self.c.db.execute("INSERT INTO estimate_lines (id, estimate_id, line_no, description, quantity, unit, unit_price, amount) VALUES (?,?,?,?,?,?,?,?)",
                              (f"eln_forged_{ln['line_no']}", "est_forged", ln["line_no"], ln["description"], ln["quantity"], ln["unit"], ln["unit_price"], ln["amount"]))
        forged = self.c.estimates.get("est_forged")
        self.assertEqual((forged["content_verified"], forged["total"]), (True, "105000.00"))
        # ... but nobody created it through Cipher, so it is never put up for approval
        with self.assertRaisesRegex(EstimateError, "estimate.created audit entry"):
            self.request("est_forged")
        self.assertEqual(self.c.ricky.propose("estimate.approve", actor_role="estimator", context={"estimate_id": "est_forged"})["decision"], "abstained")
        # nor can it borrow the real estimate's consumed approval
        self.c.approve_and_execute("estimate.approve", real["id"], actor_role="estimator", actor="estimator")
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE estimates SET status='approved', approval_id=? WHERE id='est_forged'", (self.c.estimates.get(real["id"])["approval_id"],))
        self.assertEqual(self.c.estimates.get("est_forged")["status"], "draft")
        # an audit entry that names another content hash does not vouch for it
        self.c.audit.record("estimator", "estimate.created", "estimate", "est_forged", {"content_hash": "0" * 64})
        with self.assertRaisesRegex(EstimateError, "estimate.created audit entry"):
            self.request("est_forged")
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class DownstreamTests(Base):
    def supplier(self):
        sup = self.c.add_party(kind="supplier", name="Synthetic Sheet Pile Subcontractor", destination="ACH-SIM-EST-2")
        self.c.verify_destination(sup["id"], destination="ACH-SIM-EST-2", verified_by="bank-detail-maintainer")
        return sup

    def commitment(self, sup, estimate_id, title="Synthetic subcontract"):
        return self.c.commitments.create(project_id=self.pid, supplier_id=sup["id"], title=title,
                                         sov_lines=[{"description": "Pump station", "amount": "100000", "cost_code": "XX 10 00"}],
                                         estimate_id=estimate_id, actor="pm")

    def test_commitment_approval_goes_stale_when_its_estimate_is_superseded(self):
        sup = self.supplier()
        v1 = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        self.c.approve_and_execute("estimate.approve", v1["id"], actor_role="estimator", actor="estimator")
        cmt = self.commitment(sup, v1["id"])
        ap = self.c.request_approval("commitment.execute", cmt["id"], actor_role="pm", requested_by="pm")
        self.assertFalse(ap["manifest"]["bindings"]["estimate_stale"])
        self.c.approve(ap["id"], approver="owner")
        # the next revision drops the rock-excavation exclusion (rock is now in scope)
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB1, removed_exclusions=["Rock excavation"])
        self.assertEqual(self.c.commitments.get(cmt["id"])["estimate"]["stale"], True)
        with self.assertRaises(StaleApprovalError):  # granted against v1's scope: it never executes
            self.c.execute(ap["id"], actor="pm")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.c.commitments.get(cmt["id"])["status"], "draft")
        # a fresh approval on the superseded estimate is refused at execution, and Ricky abstains
        self.assertEqual(self.c.ricky.propose("commitment.execute", actor_role="pm", context={"commitment_id": cmt["id"]})["decision"], "abstained")
        ap2 = self.c.request_approval("commitment.execute", cmt["id"], actor_role="pm", requested_by="pm")
        self.assertTrue(ap2["manifest"]["bindings"]["estimate_stale"])
        self.c.approve(ap2["id"], approver="owner")
        with self.assertRaises(CommitmentError):
            self.c.execute(ap2["id"], actor="pm")
        self.assertEqual(self.c.commitments.get(cmt["id"])["status"], "draft")
        # the current revision, once approved, carries a commitment normally
        self.c.approve_and_execute("estimate.approve", v2["id"], actor_role="estimator", actor="estimator")
        cmt2 = self.commitment(sup, v2["id"], title="Synthetic subcontract, revision 2")
        res = self.c.approve_and_execute("commitment.execute", cmt2["id"], actor_role="pm", actor="pm")
        self.assertEqual((res.result["status"], res.result["executed_amount"]), ("executed", "100000.00"))
        self.assertBooksIntact()

    def test_commitment_approval_never_executes_against_rewritten_estimate_scope(self):
        sup = self.supplier()
        est = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        self.c.approve_and_execute("estimate.approve", est["id"], actor_role="estimator", actor="estimator")
        cmt = self.commitment(sup, est["id"])
        ap = self.c.request_approval("commitment.execute", cmt["id"], actor_role="pm", requested_by="pm")
        self.c.approve(ap["id"], approver="owner")
        # a REPLACE that keeps the content hash but rewrites the scope, the price book and the total is refused ...
        sql, params = self.copy_sql("REPLACE", self.stored(est["id"]), status="draft", approval_id=None, exclusions_json="[]",
                                    price_book_ref="PB-SYN-CHEAP", total="1.00")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "never replaced"):
            self.c.db.execute(sql, params)
        self.assertEqual(self.c.commitments.get(cmt["id"])["estimate"]["stale"], False)
        # ... and a rewrite with the guards dropped leaves the estimate stale, so the approval granted
        # against its recorded scope is invalidated instead of executing
        self.c.db.execute("DROP TRIGGER estimates_content_immutable")
        self.c.db.execute("UPDATE estimates SET exclusions_json='[]', price_book_ref='PB-SYN-CHEAP' WHERE id=?", (est["id"],))
        self.assertEqual(self.c.commitments.get(cmt["id"])["estimate"]["stale"], True)
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="pm")
        self.assertEqual((self.c.approvals.get(ap["id"])["status"], self.c.commitments.get(cmt["id"])["status"]), ("invalidated", "draft"))
        self.assertEqual(self.c.ricky.propose("commitment.execute", actor_role="pm", context={"commitment_id": cmt["id"]})["decision"], "abstained")
        self.assertBooksIntact()


class ParallelEstimateTests(Base):
    def test_a_new_estimate_cannot_drop_what_the_current_one_excludes(self):
        v1 = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        self.c.approve_and_execute("estimate.approve", v1["id"], actor_role="estimator", actor="estimator")
        for kwargs, message in (
            ({}, "drop its exclusions \\['Rock excavation'\\] and its price book 'PB-SYN-2026.1'"),
            ({"price_book_ref": PB1}, "Rock excavation"),
            ({"exclusions": ["Rock excavation"]}, "price book"),
            ({"price_book_ref": PB2, "exclusions": ["Electrical service"]}, "Rock excavation"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(EstimateError, message) as caught:
                    self.create(**kwargs)
                self.assertIn(f"supersede it (supersedes='{v1['id']}')", str(caught.exception))
        # the same scope item priced from a newer revision of the same drawing is still the same scope
        rev2 = self.c.evidence.add_revision(document_id=self.doc["id"], content=b"synthetic drawing A rev 2", actor="engineer")
        with self.assertRaisesRegex(EstimateError, "already prices \\['Pump station, complete'\\] from this document"):
            self.c.estimates.create(self.pid, rev2["id"], LUMP, "estimator")
        self.assertEqual((self.count(), len(self.audit_actions("estimate.created"))), (1, 1))
        # keeping the exclusion (written differently) and naming a price book is allowed, and bound into the manifest
        parallel = self.c.estimates.create(self.pid, rev2["id"], LUMP, "estimator", price_book_ref=PB2,
                                           exclusions=["rock  EXCAVATION", "Electrical service"])
        b = self.request(parallel["id"])["manifest"]["bindings"]
        self.assertEqual(b["overlapping_estimates"], [{
            "estimate_id": v1["id"], "content_hash": v1["content_hash"], "same_document": True, "shared_lines": ["Pump station, complete"],
            "scope_recorded_by": v1["id"], "price_book_ref": PB1, "exclusions_not_carried": [],
        }])
        self.assertEqual(json.loads(self.audit_actions("estimate.created", parallel["id"])[0]["payload_json"])["overlapping_estimates"], [v1["id"]])
        # the governed way to drop the exclusion is to supersede v1, where the removal is recorded; the parallel
        # estimate that still excludes it is then shown to whoever approves the new revision
        v2 = self.c.estimates.create(self.pid, rev2["id"], LUMP, "estimator", v1["id"], price_book_ref=PB1, removed_exclusions=["Rock excavation"])
        self.assertEqual((v2["revision"], v2["supersession"]["removed_exclusions"]), (2, ["Rock excavation"]))
        b2 = self.request(v2["id"])["manifest"]["bindings"]
        self.assertEqual([(o["estimate_id"], o["exclusions_not_carried"], o["price_book_ref"]) for o in b2["overlapping_estimates"]],
                         [(parallel["id"], ["rock EXCAVATION", "Electrical service"], PB2)])
        self.assertBooksIntact()

    def test_other_scope_and_other_documents_are_allowed_and_flagged(self):
        v1 = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        vault = [{"description": "Valve vault", "quantity": "1", "unit": "LS", "unit_price": "9000"}]
        other_scope = self.create(lines=vault)  # same drawing, other scope
        doc_b = self.c.evidence.register_document(project_id=self.pid, kind="drawing", title="Synthetic drawing B", actor="estimator")
        rev_b = self.c.evidence.add_revision(document_id=doc_b["id"], content=b"synthetic drawing B rev 1", actor="estimator")
        other_doc = self.c.estimates.create(self.pid, rev_b["id"], LUMP, "estimator")  # same scope item, another drawing
        overlaps = self.request(other_scope["id"])["manifest"]["bindings"]["overlapping_estimates"]
        self.assertEqual([(o["estimate_id"], o["same_document"], o["shared_lines"], o["exclusions_not_carried"]) for o in overlaps],
                         [(v1["id"], True, [], ["Rock excavation"])])
        overlaps = self.request(other_doc["id"])["manifest"]["bindings"]["overlapping_estimates"]
        self.assertEqual([(o["estimate_id"], o["same_document"], o["shared_lines"], o["exclusions_not_carried"], o["price_book_ref"]) for o in overlaps],
                         [(v1["id"], False, ["Pump station, complete"], ["Rock excavation"], PB1)])
        # a parallel estimate that appears after a grant changes what the approver saw: that approval goes stale
        ap = self.granted(other_scope["id"])
        self.create(lines=[{**vault[0], "unit_price": "9500"}])
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="estimator")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.c.estimates.get(other_scope["id"])["status"], "draft")

    def test_a_raw_successor_cannot_clear_the_way_for_a_parallel_estimate(self):
        v1 = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        # plain SQL supersedes v1 with a row that has no lines, no exclusion and no price book
        self.c.db.execute(self.RAW_INSERT, ("est_raw_v2", self.pid, self.rev["id"], 2, v1["id"], "draft", None))
        self.assertEqual(self.c.estimates.get(v1["id"])["status"], "superseded")
        # the raw row stands for its chain's recorded scope: v1's line items, exclusions and price book
        message = "estimate est_raw_v2 already prices \\['Pump station, complete'\\] .* exclusions \\['Rock excavation'\\] and its price book"
        with self.assertRaisesRegex(EstimateError, message):
            self.create()
        # giving the raw row other lines changes nothing: it is not trusted, so v1's line items still count
        self.c.db.execute(f"INSERT INTO estimate_lines {LINE_COLUMNS} VALUES ('eln_raw_v2_1','est_raw_v2',1,'Something else','1','LS','1.00','1.00')")
        with self.assertRaisesRegex(EstimateError, message):
            self.create()
        with self.assertRaisesRegex(EstimateError, "Rock excavation"):
            self.create(price_book_ref=PB2)
        self.assertEqual(self.count(), 2)
        ok = self.create(price_book_ref=PB2, exclusions=["Rock excavation"])
        overlaps = self.request(ok["id"])["manifest"]["bindings"]["overlapping_estimates"]
        self.assertEqual([(o["estimate_id"], o["scope_recorded_by"], o["price_book_ref"], o["exclusions_not_carried"]) for o in overlaps],
                         [("est_raw_v2", v1["id"], PB1, [])])


class InputValidationTests(Base):
    def test_invalid_lines(self):
        ok = {"description": "Item", "quantity": "1", "unit": "LS", "unit_price": "1"}
        bad_lines = [
            [], None, "LS", ["not an object"],
            [{"description": "Item", "unit": "LS", "unit_price": "1"}],
            [{**ok, "description": "  "}],
            [{**ok, "quantity": 1.5}],
            [{**ok, "unit_price": "-1"}],
            [{**ok, "quantity": "-0.001"}],
            [{**ok, "quantity": "NaN"}],
            [{**ok, "unit_price": "Infinity"}],
            [{**ok, "quantity": "1e40"}],
            [{**ok, "unit_price": "twelve"}],
        ]
        for lines in bad_lines:
            with self.subTest(lines=lines), self.assertRaises(EstimateError):
                self.c.estimates.create(self.pid, self.rev["id"], lines, "estimator")
        # descriptions are hashed and shown to the approver, so they must be text, not a stringified object
        for description in ({"x": 1}, ["Item"], 5, True, b"Item"):
            with self.subTest(description=description), self.assertRaisesRegex(EstimateError, "description must be text"):
                self.c.estimates.create(self.pid, self.rev["id"], [{**ok, "description": description}], "estimator")
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.audit_actions("estimate.created"), [])

    def test_totals_beyond_the_money_range_are_estimate_errors(self):
        nine_t = {"description": "Oversized item", "quantity": "1", "unit": "LS", "unit_price": "9000000000000"}
        with self.assertRaisesRegex(EstimateError, "out of range"):  # each line fits, the subtotal does not
            self.create(lines=[nine_t, {**nine_t, "description": "Second oversized item"}])
        with self.assertRaisesRegex(EstimateError, "out of range"):  # the subtotal fits, subtotal + contingency does not
            self.create(lines=[{**nine_t, "unit_price": "9900000000000"}], contingency_rate="0.5")
        with self.assertRaisesRegex(EstimateError, "line 1"):  # a single line amount beyond range
            self.create(lines=[{**nine_t, "quantity": "2"}])
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.audit_actions("estimate.created"), [])
        est = self.create(lines=[{**nine_t, "unit_price": "6000000000000"}], contingency_rate="0.5")  # within range: accepted exactly
        self.assertEqual((est["subtotal"], est["contingency"], est["total"]), ("6000000000000.00", "3000000000000.00", "9000000000000.00"))

    def test_quantities_are_bounded_and_line_amounts_are_rounded_once(self):
        for qty in ("1.004999999999999999999999999999", "1234567890.1234567", "1E-16", "0.0000000000000001"):
            with self.subTest(quantity=qty), self.assertRaisesRegex(EstimateError, "line 1: quantity .* more precise"):
                self.create(lines=[{"description": "Item", "quantity": qty, "unit": "EA", "unit_price": "3.00"}])
        self.assertEqual(self.count(), 0)
        # up to 15 significant digits are kept exactly; trailing zeros are not precision
        est = self.create(lines=[{"description": "Item", "quantity": "1.00499999999999", "unit": "EA", "unit_price": "3.00"},
                                 {"description": "Other item", "quantity": "2.500000000000000000000", "unit": "EA", "unit_price": "4.00"}])
        self.assertEqual([(ln["quantity"], ln["amount"]) for ln in est["lines"]], [("1.00499999999999", "3.01"), ("2.5", "10.00")])
        # this product has 30 significant digits (exactly 1122775287813.55499999999999964); rounding it to the
        # default 28 digits before rounding to cents would give 1122775287813.56
        est = self.create(lines=[{"description": "Long product", "quantity": "0.113680997878332", "unit": "EA", "unit_price": "9876543210987.77"}])
        self.assertEqual((est["lines"][0]["amount"], est["subtotal"], est["total"], est["content_verified"]),
                         ("1122775287813.55", "1122775287813.55", "1122775287813.55", True))
        self.assertEqual(self.request(est["id"])["manifest"]["amounts"]["total"], "1122775287813.55")

    def test_invisible_text_does_not_count_as_text(self):
        sf = [{"description": "Cofferdam wall", "quantity": "1200", "unit": "SF", "unit_price": "50"}]
        for basis in ("​", " ​⁠ ", "﻿", "‍‌", "­"):
            with self.subTest(basis=ascii(basis)), self.assertRaisesRegex(EstimateError, "unit/scale"):
                self.create(lines=sf, measurement_basis=basis)
        for kwargs in ({"price_book_ref": "​"}, {"exclusions": ["​"]}, {"inclusions": ["Dewatering", "⁠ "]}):
            with self.subTest(kwargs=ascii(kwargs)), self.assertRaisesRegex(EstimateError, "visible"):
                self.create(**kwargs)
        with self.assertRaisesRegex(EstimateError, "description is required"):
            self.create(lines=[{"description": "​​", "quantity": "1", "unit": "LS", "unit_price": "1"}])
        self.assertEqual((self.count(), self.audit_actions("estimate.created")), (0, []))
        # look-alike spellings are the same scope item: they neither count twice nor hide a removal
        for twin in ("Rock​ excavation", "Ｒock excavation", "rock excavation"):
            with self.subTest(twin=ascii(twin)), self.assertRaisesRegex(EstimateError, "more than once"):
                self.create(exclusions=["Rock excavation", twin])
        v1 = self.create(price_book_ref=PB1, exclusions=["Rock excavation"])
        with self.assertRaisesRegex(EstimateError, "still excluded"):
            self.create(supersedes=v1["id"], price_book_ref=PB1, exclusions=["Rock excavation​"], removed_exclusions=["Rock excavation"])
        v2 = self.create(supersedes=v1["id"], price_book_ref=PB1, exclusions=["Ｒock excavation"], contingency_rate="0.01")
        self.assertEqual((v2["supersession"]["removed_exclusions"], v2["supersession"]["added_exclusions"]), ([], []))
        # a visible basis with a stray zero-width character in it is still a basis
        est = self.create(lines=sf, measurement_basis="​" + BASIS)
        self.assertEqual(est["measurement_basis"], "​" + BASIS)

    def test_invalid_scope_and_reference_inputs(self):
        bad_kwargs = [
            {"inclusions": "Dewatering"},
            {"exclusions": ["Rock excavation", "rock  EXCAVATION"]},
            {"exclusions": [""]},
            {"exclusions": [5]},
            {"exclusions": {"Rock excavation"}},
            {"inclusions": ["Dewatering"], "exclusions": ["dewatering"]},
            {"price_book_ref": ""},
            {"price_book_ref": 5},
            {"measurement_basis": 5},
        ]
        for kwargs in bad_kwargs:
            with self.subTest(kwargs=kwargs), self.assertRaises(EstimateError):
                self.create(**kwargs)
        with self.assertRaisesRegex(EstimateError, "unknown project"):
            self.c.estimates.create("prj_missing", self.rev["id"], LUMP, "estimator")
        with self.assertRaisesRegex(EstimateError, "unknown document revision"):
            self.c.estimates.create(self.pid, "rev_missing", LUMP, "estimator")
        other = self.c.create_project(name="Other synthetic project", entity=ENTITY, budget="1000")
        odoc = self.c.evidence.register_document(project_id=other["id"], kind="drawing", title="Other drawing", actor="estimator")
        orev = self.c.evidence.add_revision(document_id=odoc["id"], content=b"other drawing rev 1", actor="estimator")
        with self.assertRaisesRegex(EstimateError, "another project"):
            self.c.estimates.create(self.pid, orev["id"], LUMP, "estimator")
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.audit_actions("estimate.created"), [])
        self.assertBooksIntact()


class MigrationTests(unittest.TestCase):
    def test_entry_is_registered_and_applied(self):
        c = Cipher()
        status = {v["name"]: v for v in c.db.schema_status()["versions"]}
        for name in ESTIMATE_SCHEMA_NAMES:
            self.assertTrue(status[name]["applied"] and status[name]["checksum_matches"], name)
        self.assertLess(status[STRUCTURE_SCHEMA_NAME]["version"], status[LIFECYCLE_SCHEMA_NAME]["version"])
        self.assertLess(status[LIFECYCLE_SCHEMA_NAME]["version"], status[NO_REPLACE_SCHEMA_NAME]["version"])
        cols = {r["name"] for r in c.db.query("PRAGMA table_info(estimates)")}
        self.assertTrue({"price_book_ref", "inclusions_json", "exclusions_json", "contingency_rate", "subtotal", "measurement_basis"} <= cols)

    def test_legacy_workspace_upgrades_in_place_and_keeps_its_estimates(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "legacy.sqlite")
        saved = list(SCHEMA_CATALOG)
        try:
            SCHEMA_CATALOG[:] = [e for e in saved if e[1] not in ESTIMATE_SCHEMA_NAMES]
            old = Cipher(path)
            try:
                project = old.create_project(name="Legacy synthetic project", entity=ENTITY, budget="100000")
                doc = old.evidence.register_document(project_id=project["id"], kind="drawing", title="Legacy drawing", actor="estimator")
                rev = old.evidence.add_revision(document_id=doc["id"], content=b"legacy drawing rev 1", actor="estimator")
                legacy = {
                    "est_legacy_ls": ([("Pump station", "1", "LS", "40000.00", "40000.00"), ("Valves", "3", "ea", "100.00", "300.00")], "40300.00"),
                    "est_legacy_sf": ([("Cofferdam wall", "1200", "SF", "50.00", "60000.00")], "60000.00"),
                }
                with old.db.transaction() as conn:
                    for est_id, (lines, est_total) in legacy.items():
                        hashed = [{"line_no": i, "description": d_, "quantity": q, "unit": u, "unit_price": p, "amount": a} for i, (d_, q, u, p, a) in enumerate(lines, 1)]
                        h = hash_json({"document_revision_id": rev["id"], "document_hash": rev["content_hash"], "lines": hashed})
                        conn.execute("INSERT INTO estimates (id, project_id, document_revision_id, revision, supersedes, status, total, content_hash, created_at) VALUES (?,?,?,1,NULL,'draft',?,?,'2026-10-01T00:00:00Z')",
                                     (est_id, project["id"], rev["id"], est_total, h))
                        for ln in hashed:
                            conn.execute("INSERT INTO estimate_lines (id, estimate_id, line_no, description, quantity, unit, unit_price, amount) VALUES (?,?,?,?,?,?,?,?)",
                                         (f"eln_{est_id}_{ln['line_no']}", est_id, ln["line_no"], ln["description"], ln["quantity"], ln["unit"], ln["unit_price"], ln["amount"]))
                        # the API of that release audited each creation, as it does now
                        old.audit.record("estimator", "estimate.created", "estimate", est_id, {"total": est_total, "content_hash": h})
            finally:
                old.db.close()
        finally:
            SCHEMA_CATALOG[:] = saved
        c = Cipher(path)
        self.addCleanup(c.db.close)
        self.assertEqual(c.db.schema_status()["pending"], [])
        est = c.estimates.get("est_legacy_ls")
        self.assertEqual((est["subtotal"], est["contingency"], est["total"], est["contingency_rate"], est["exclusions"], est["content_verified"]),
                         ("40300.00", "0.00", "40300.00", "0.000000", [], True))
        self.assertEqual([ln["unit"] for ln in est["lines"]], ["LS", "ea"])  # stored history is not rewritten
        c.approve_and_execute("estimate.approve", "est_legacy_ls", actor_role="estimator", actor="estimator")
        self.assertEqual(c.estimates.get("est_legacy_ls")["status"], "approved")
        # a legacy measured line without a basis verifies but cannot be approved until re-measured
        self.assertTrue(c.estimates.get("est_legacy_sf")["content_verified"])
        with self.assertRaisesRegex(EstimateError, "unit/scale"):
            c.request_approval("estimate.approve", "est_legacy_sf", actor_role="estimator", requested_by="estimator")
        nxt = c.estimates.create(project["id"], rev["id"], [{"description": "Cofferdam wall", "quantity": "1200", "unit": "SF", "unit_price": "50"}],
                                 "estimator", "est_legacy_sf", measurement_basis=BASIS)
        self.assertEqual((nxt["revision"], nxt["total"], c.estimates.get("est_legacy_sf")["status"]), (2, "60000.00", "superseded"))
        with self.assertRaises(sqlite3.DatabaseError):  # the upgraded workspace has the guards too
            c.db.execute("UPDATE estimate_lines SET amount='1.00' WHERE estimate_id='est_legacy_ls'")
        approved_ap = c.estimates.get("est_legacy_ls")["approval_id"]
        with self.assertRaises(sqlite3.DatabaseError):  # another estimate's consumed approval is not this one's
            c.db.execute("UPDATE estimates SET status='approved', approval_id=? WHERE id=?", (approved_ap, nxt["id"]))
        triggers = {r["name"] for r in c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('estimates', 'estimate_lines')")}
        self.assertTrue({"estimates_status_transitions", "estimates_insert_rules", "estimates_successor_supersedes",
                         "estimates_no_replace", "estimate_lines_no_replace"} <= triggers)
        self.assertNotIn("estimates_status_lifecycle", triggers)  # the shape-only predecessor was replaced
        legacy_row = c.db.one("SELECT * FROM estimates WHERE id='est_legacy_ls'")
        cols = list(legacy_row)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "never replaced"):  # nor can a legacy row be replaced
            c.db.execute(f"REPLACE INTO estimates ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         tuple({**legacy_row, "status": "draft", "approval_id": None}[k] for k in cols))
        self.assertEqual(c.estimates.get("est_legacy_ls")["status"], "approved")
        self.assertTrue(c.audit.verify_chain()["ok"])


if __name__ == "__main__":
    unittest.main()
