"""Asset register and depreciation: golden schedule, reversals, disposal and adversarial cases."""
import sqlite3
import unittest
from decimal import Decimal

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.assets import AssetError, straight_line_schedule
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.service import Cipher


def accumulated(c: Cipher) -> Decimal:
    """1590 is a contra-asset: report its credit balance as a positive number."""
    act = c.ledger.account_activity("1590")
    return act["credit"] - act["debit"]


class Fixture:
    """One customer, one project and monthly periods P0 (Sep), P1 (Oct), P2 (Nov) 2026."""

    def __init__(self):
        self.c = Cipher()
        self.customer = self.c.add_party(kind="customer", name="Synthetic Owner", destination=None)
        self.project = self.c.create_project(name="Pump station", entity="S&A (synthetic)", budget="50000", customer_id=self.customer["id"])
        self.c.open_period("P0", "September 2026", "2026-09-01", "2026-09-30")
        self.c.open_period("P1", "October 2026", "2026-10-01", "2026-10-31")
        self.c.open_period("P2", "November 2026", "2026-11-01", "2026-11-30")
        self.assets = self.c.plugin("asset")

    def register(self, **over):
        params = dict(project_id=self.project["id"], description="Trench box", cost="12000", in_service_date="2026-10-01",
                      useful_life_months=12, salvage_value="0", actor="owner")
        params.update(over)
        return self.assets.register_asset(**params)

    def capitalized(self, **over):
        a = self.register(**over)
        self.c.approve_and_execute("asset.capitalise", a["id"], period_id="P1")
        return self.assets.get_asset(a["id"])


class ScheduleMathTests(unittest.TestCase):
    def test_final_month_absorbs_rounding_residual(self):
        self.assertEqual([str(x) for x in straight_line_schedule("1000", "0", 3)], ["333.33", "333.33", "333.34"])
        self.assertEqual([str(x) for x in straight_line_schedule("12000", "0", 12)], ["1000.00"] * 12)
        self.assertEqual([str(x) for x in straight_line_schedule("10000", "1000", 7)], ["1285.71"] * 6 + ["1285.74"])
        self.assertEqual([str(x) for x in straight_line_schedule("500", "500", 4)], ["0.00"] * 4)

    def test_schedule_always_sums_exactly_and_never_goes_negative(self):
        for cost, salvage, life in (("0.06", "0", 12), ("0.01", "0", 3), ("99999.99", "0.01", 37), ("1", "0", 1200)):
            sched = straight_line_schedule(cost, salvage, life)
            self.assertEqual(len(sched), life)
            self.assertEqual(sum(sched), Decimal(cost) - Decimal(salvage))
            self.assertTrue(all(x >= 0 for x in sched), (cost, salvage, life))

    def test_schedule_rejects_bad_life_and_salvage(self):
        with self.assertRaises(AssetError):
            straight_line_schedule("1000", "0", 0)
        with self.assertRaises(AssetError):
            straight_line_schedule("1000", "1000.01", 3)


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.c = self.f.c
        self.p = self.f.assets

    def test_register_defaults_and_shape(self):
        a = self.f.register()
        self.assertTrue(a["id"].startswith("ast_"))
        self.assertEqual(a["status"], "registered")
        self.assertEqual(a["version"], 1)
        self.assertEqual(a["cost"], "12000.00")
        self.assertEqual(a["salvage_value"], "0.00")
        self.assertEqual(a["method"], "straight_line")
        self.assertEqual(a["useful_life_months"], 12)
        self.assertEqual(a["depreciable_base"], "12000.00")
        self.assertEqual(a["monthly_amount"], "1000.00")
        self.assertEqual(a["final_month_amount"], "1000.00")
        self.assertEqual(a["accumulated_depreciation"], "0.00")
        self.assertEqual(a["remaining_depreciable"], "12000.00")
        self.assertEqual(a["net_book_value"], "12000.00")
        self.assertEqual(a["runs"], [])
        self.assertFalse(a["fully_depreciated"])
        self.assertFalse(a["over_depreciated"])
        self.assertEqual(len(a["content_hash"]), 64)
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        self.assertEqual([e["action"] for e in self.c.audit.entries(entity_type="asset", entity_id=a["id"])], ["asset.registered"])

    def test_register_rejects_invalid_input(self):
        cases = {
            "float cost": dict(cost=12000.0),
            "zero cost": dict(cost="0"),
            "negative cost": dict(cost="-1"),
            "non-decimal cost": dict(cost="twelve"),
            "negative salvage": dict(salvage_value="-5"),
            "salvage above cost": dict(salvage_value="12000.01"),
            "bad month": dict(in_service_date="2026-13-01"),
            "wrong date format": dict(in_service_date="10/01/2026"),
            "compact date": dict(in_service_date="20261001"),
            "zero life": dict(useful_life_months=0),
            "text life": dict(useful_life_months="a year"),
            "bool life": dict(useful_life_months=True),
            "float life": dict(useful_life_months=12.0),
            "absurd life": dict(useful_life_months=1201),
            "unknown method": dict(method="double_declining"),
            "blank description": dict(description="   "),
            "unknown project": dict(project_id="prj_missing"),
        }
        for label, over in cases.items():
            with self.subTest(label):
                with self.assertRaises(AssetError):
                    self.f.register(**over)
        self.assertEqual(self.p.list_assets(self.f.project["id"]), [])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_register_rejects_duplicate_description_until_disposed(self):
        a = self.f.register()
        with self.assertRaises(AssetError):
            self.f.register()
        with self.assertRaises(AssetError):
            self.f.register(description="  trench BOX ")
        other = self.c.create_project(name="Other", entity="E", budget="1")
        self.f.register(project_id=other["id"])  # same description on another project is fine
        self.c.approve_and_execute("asset.capitalise", a["id"], period_id="P1")
        self.c.approve_and_execute("asset.dispose", a["id"], period_id="P1")
        again = self.f.register()  # a disposed asset no longer blocks the description
        self.assertEqual(again["status"], "registered")
        self.assertEqual(len(self.p.list_assets(self.f.project["id"])), 2)

    def test_life_accepts_digit_string(self):
        a = self.f.register(useful_life_months="24", cost="2400")
        self.assertEqual(a["useful_life_months"], 24)
        self.assertEqual(a["monthly_amount"], "100.00")


class CapitalizationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.c = self.f.c
        self.p = self.f.assets

    def test_capitalize_posts_synthetic_purchase_and_activates(self):
        a = self.f.register()
        r = self.c.approve_and_execute("asset.capitalise", a["id"], period_id="P1")
        self.assertFalse(r.replayed)
        self.assertEqual(r.result["status"], "active")
        self.assertEqual(r.result["cost"], "12000.00")
        j = self.c.ledger.journal(r.result["journal_id"])
        self.assertEqual(j["period_id"], "P1")
        self.assertEqual(j["source_type"], "asset")
        self.assertEqual(j["source_id"], a["id"])
        self.assertIsNotNone(j["approval_id"])
        self.assertEqual([(l["account_code"], l["debit"], l["credit"]) for l in j["lines"]], [("1500", "12000.00", "0.00"), ("1000", "0.00", "12000.00")])
        self.assertEqual(self.c.ledger.balance("1500"), Decimal("12000.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-12000.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        a = self.p.get_asset(a["id"])
        self.assertEqual(a["status"], "active")
        self.assertEqual(a["capitalisation_journal_id"], j["id"])
        self.assertEqual(a["version"], 1)
        with self.assertRaises(AssetError):  # cannot capitalize twice
            self.c.approve_and_execute("asset.capitalise", a["id"], period_id="P1")
        self.assertEqual(self.c.ledger.balance("1500"), Decimal("12000.00"))
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_capitalize_approval_goes_stale_when_asset_is_edited(self):
        a = self.f.register()
        ap = self.c.request_approval("asset.capitalise", a["id"])
        self.c.approve(ap["id"])
        self.assertEqual(ap["manifest"]["bindings"]["asset_version"], 1)
        edited = self.p.update_asset(a["id"], "owner", description="Trench box, 8 ft")
        self.assertEqual(edited["version"], 2)
        self.assertNotEqual(edited["content_hash"], a["content_hash"])
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.p.get_asset(a["id"])["status"], "registered")
        self.assertEqual(self.c.ledger.trial_balance()["journal_count"], 0)
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        # a fresh approval against the edited record executes normally
        r = self.c.approve_and_execute("asset.capitalise", a["id"], period_id="P1")
        self.assertEqual(r.result["status"], "active")

    def test_capitalize_into_closed_period_is_rejected(self):
        a = self.f.register()
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.approve_and_execute("asset.capitalise", a["id"], period_id="P1")
        self.assertEqual(self.p.get_asset(a["id"])["status"], "registered")
        self.assertEqual(self.c.ledger.balance("1500"), Decimal("0.00"))
        # the still-open period works, and current_period() is used when none is given
        r = self.c.approve_and_execute("asset.capitalise", a["id"])
        self.assertEqual(self.c.ledger.journal(r.result["journal_id"])["period_id"], "P2")


class DepreciationRunTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.c = self.f.c
        self.p = self.f.assets
        self.a = self.f.capitalized()

    def test_golden_schedule_no_charge_before_in_service_then_first_month(self):
        run0 = self.p.schedule_run(self.a["id"], "P0", "owner")
        self.assertEqual(run0["status"], "no_charge")
        self.assertEqual(run0["amount"], "0.00")
        self.assertEqual(run0["sequence"], 0)
        self.assertEqual(run0["charge_month"], "2026-09")
        self.assertIsNone(run0["journal_id"])
        self.assertIn("precedes", run0["note"])
        with self.assertRaises(AssetError):  # nothing to post, ever
            self.c.approve_and_execute("asset.post_depreciation", run0["id"], period_id="P0")
        self.assertEqual(self.c.ledger.journals(source_type="asset_run"), [])
        # the database refuses to attach a journal to a no-charge run even if code tried
        cap_journal = self.a["capitalisation_journal_id"]
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE asset_depreciation_runs SET journal_id=? WHERE id=?", (cap_journal, run0["id"]))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE asset_depreciation_runs SET status='posted' WHERE id=?", (run0["id"],))
        self.assertEqual(self.p.get_run(run0["id"])["status"], "no_charge")

        run1 = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.assertEqual(run1["status"], "draft")
        self.assertEqual(run1["amount"], "1000.00")
        self.assertEqual(run1["sequence"], 1)
        self.assertEqual(run1["charge_month"], "2026-10")
        self.assertEqual(run1["asset_version"], 1)
        self.assertFalse(run1["stale"])
        r = self.c.approve_and_execute("asset.post_depreciation", run1["id"], period_id="P1")
        self.assertEqual(r.result["status"], "posted")
        self.assertEqual(r.result["amount"], "1000.00")
        j = self.c.ledger.journal(r.result["journal_id"])
        self.assertEqual([(l["account_code"], l["debit"], l["credit"]) for l in j["lines"]], [("5200", "1000.00", "0.00"), ("1590", "0.00", "1000.00")])
        self.assertEqual(j["source_type"], "asset_run")
        self.assertEqual(j["source_id"], run1["id"])
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("1000.00"))
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))
        self.assertEqual(self.c.ledger.balance("1590"), Decimal("-1000.00"))  # contra-asset shown debit-natural
        a = self.p.get_asset(self.a["id"])
        self.assertEqual(a["accumulated_depreciation"], "1000.00")
        self.assertEqual(a["net_book_value"], "11000.00")
        self.assertEqual(a["months_posted"], 1)
        self.assertEqual(self.p.get_run(run1["id"])["journal_id"], j["id"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_reverse_then_replacement_run(self):
        run1 = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.c.approve_and_execute("asset.post_depreciation", run1["id"], period_id="P1")
        with self.assertRaises(AssetError):  # duplicate while a posted run exists
            self.p.schedule_run(self.a["id"], "P1", "owner")
        rev = self.c.approve_and_execute("asset.reverse_depreciation", run1["id"], period_id="P1")
        self.assertEqual(rev.result["status"], "reversed")
        rj = self.c.ledger.journal(rev.result["reversal_journal_id"])
        self.assertEqual(rj["reversal_of"], self.p.get_run(run1["id"])["journal_id"])
        self.assertEqual(self.p.get_run(run1["id"])["reversal_journal_id"], rj["id"])
        self.assertEqual([(l["account_code"], l["debit"], l["credit"]) for l in rj["lines"]], [("5200", "0.00", "1000.00"), ("1590", "1000.00", "0.00")])
        self.assertEqual(accumulated(self.c), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("0.00"))
        self.assertEqual(self.p.get_asset(self.a["id"])["net_book_value"], "12000.00")
        with self.assertRaises(AssetError):  # cannot reverse twice
            self.c.approve_and_execute("asset.reverse_depreciation", run1["id"], period_id="P1")
        # original posted journals are untouched
        self.assertEqual(self.c.ledger.journal(self.p.get_run(run1["id"])["journal_id"])["lines"][0]["debit"], "1000.00")

        run1b = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.assertEqual(run1b["replaced_run_id"], run1["id"])
        self.assertEqual(run1b["amount"], "1000.00")
        self.assertEqual(run1b["status"], "draft")
        self.c.approve_and_execute("asset.post_depreciation", run1b["id"], period_id="P1")
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("1000.00"))
        self.assertEqual(self.c.ledger.account_activity("1590"), {"debit": Decimal("1000.00"), "credit": Decimal("2000.00")})
        a = self.p.get_asset(self.a["id"])
        self.assertEqual(a["accumulated_depreciation"], "1000.00")
        self.assertEqual([r["status"] for r in a["runs"]], ["reversed", "posted"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_reversal_cannot_be_dated_before_the_run_it_reverses(self):
        run1 = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.c.approve_and_execute("asset.post_depreciation", run1["id"], period_id="P1")
        ap = self.c.request_approval("asset.reverse_depreciation", run1["id"])
        self.assertIn("2026-10-01", ap["manifest"]["bindings"]["target_rule"])
        self.c.approve(ap["id"])
        with self.assertRaises(AssetError) as ctx:  # P0 (September) starts before the October run
            self.c.execute(ap["id"], period_id="P0")
        self.assertIn("cannot be dated before", str(ctx.exception))
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")  # the failed command rolled back
        self.assertEqual(self.p.get_run(run1["id"])["status"], "posted")
        self.assertEqual(self.c.ledger.journals(period_id="P0"), [])
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))
        rev = self.c.execute(ap["id"], period_id="P2")  # a later period is fine
        self.assertEqual((rev.result["status"], rev.result["period_id"]), ("reversed", "P2"))
        self.assertEqual(self.c.ledger.journal(rev.result["reversal_journal_id"])["period_id"], "P2")
        self.assertEqual(accumulated(self.c), Decimal("0.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_reverse_requires_posted_run(self):
        run1 = self.p.schedule_run(self.a["id"], "P1", "owner")
        with self.assertRaises(AssetError):
            self.c.approve_and_execute("asset.reverse_depreciation", run1["id"], period_id="P1")
        run0 = self.p.schedule_run(self.a["id"], "P0", "owner")
        with self.assertRaises(AssetError):
            self.c.approve_and_execute("asset.reverse_depreciation", run0["id"], period_id="P0")
        self.assertEqual(self.c.ledger.journals(source_type="asset_run"), [])

    def test_duplicate_runs_rejected_until_reversed_or_canceled(self):
        run1 = self.p.schedule_run(self.a["id"], "P1", "owner")
        with self.assertRaises(AssetError):
            self.p.schedule_run(self.a["id"], "P1", "owner")
        run0 = self.p.schedule_run(self.a["id"], "P0", "owner")
        with self.assertRaises(AssetError):  # no-charge runs count too
            self.p.schedule_run(self.a["id"], "P0", "owner")
        # the partial unique index (per asset per calendar month) backs the Python check
        raw = "INSERT INTO asset_depreciation_runs (id, asset_id, period_id, charge_month, sequence, amount, asset_version, status, content_hash, created_at) VALUES (?,?,?,?,1,'1000.00',1,'draft','h','t')"
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute(raw, ("dep_x", self.a["id"], "P1", "2026-10"))
        self.c.open_period("P1adj", "October 2026 adjustments", "2026-10-01", "2026-10-31")
        with self.assertRaises(sqlite3.IntegrityError):  # a different period row for the same month is still the same month
            self.c.db.execute(raw, ("dep_y", self.a["id"], "P1adj", "2026-10"))
        with self.assertRaises(sqlite3.IntegrityError):  # the month must be the period's own month
            self.c.db.execute(raw, ("dep_z", self.a["id"], "P2", "2026-10"))
        with self.assertRaises(sqlite3.IntegrityError):  # a run cannot be moved to another month
            self.c.db.execute("UPDATE asset_depreciation_runs SET charge_month='2026-11' WHERE id=?", (run1["id"],))
        self.assertEqual(self.p.get_run(run1["id"])["charge_month"], "2026-10")
        canceled = self.p.cancel_run(run1["id"], "owner", reason="scheduled by mistake")
        self.assertEqual(canceled["status"], "cancelled")
        with self.assertRaises(AssetError):  # canceled runs are final
            self.p.cancel_run(run1["id"], "owner")
        replacement = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.assertEqual(replacement["replaced_run_id"], run1["id"])
        self.assertEqual(replacement["status"], "draft")
        self.assertEqual(self.p.cancel_run(run0["id"], "owner")["status"], "cancelled")
        self.assertEqual(self.p.schedule_run(self.a["id"], "P0", "owner")["status"], "no_charge")
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_rounding_residual_lands_in_final_month_and_then_no_charge(self):
        a = self.f.capitalized(description="Laser level", cost="1000", useful_life_months=3)
        self.c.open_period("P3", "December 2026", "2026-12-01", "2026-12-31")
        self.c.open_period("P4", "January 2027", "2027-01-01", "2027-01-31")
        amounts = []
        for pid in ("P1", "P2", "P3"):
            run = self.p.schedule_run(a["id"], pid, "owner")
            amounts.append(run["amount"])
            self.c.approve_and_execute("asset.post_depreciation", run["id"], period_id=pid)
        self.assertEqual(amounts, ["333.33", "333.33", "333.34"])
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("1000.00"))
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))
        a = self.p.get_asset(a["id"])
        self.assertEqual(a["accumulated_depreciation"], "1000.00")
        self.assertEqual(a["net_book_value"], "0.00")
        self.assertTrue(a["fully_depreciated"])
        self.assertEqual(a["months_posted"], 3)
        late = self.p.schedule_run(a["id"], "P4", "owner")
        self.assertEqual(late["status"], "no_charge")
        self.assertEqual(late["amount"], "0.00")
        self.assertEqual(late["sequence"], 4)
        self.assertIn("fully depreciated", late["note"])
        with self.assertRaises(AssetError):
            self.c.approve_and_execute("asset.post_depreciation", late["id"], period_id="P4")
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("1000.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_salvage_reduces_depreciable_base(self):
        a = self.f.capitalized(description="Compactor", cost="10000", salvage_value="1000", useful_life_months=36, in_service_date="2026-10-15")
        self.assertEqual(a["depreciable_base"], "9000.00")
        self.assertEqual(a["monthly_amount"], "250.00")
        run = self.p.schedule_run(a["id"], "P1", "owner")  # mid-month in-service date still charges the full month
        self.assertEqual((run["sequence"], run["amount"]), (1, "250.00"))
        self.c.approve_and_execute("asset.post_depreciation", run["id"], period_id="P1")
        self.assertEqual(self.p.get_asset(a["id"])["net_book_value"], "9750.00")

    def test_run_requires_active_asset_and_monthly_period(self):
        registered = self.f.register(description="Not yet bought")
        with self.assertRaises(AssetError):
            self.p.schedule_run(registered["id"], "P1", "owner")
        with self.assertRaises(AssetError):
            self.p.schedule_run(self.a["id"], "P9", "owner")  # unknown period
        self.c.open_period("Q4", "Quarter", "2026-10-01", "2026-12-31")
        with self.assertRaises(AssetError):
            self.p.schedule_run(self.a["id"], "Q4", "owner")
        with self.assertRaises(AssetError):
            self.p.schedule_run("ast_missing", "P1", "owner")
        self.assertEqual(self.p.get_asset(self.a["id"])["runs"], [])

    def test_posting_into_closed_period_is_rejected(self):
        run1 = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.approve_and_execute("asset.post_depreciation", run1["id"], period_id="P1")
        run1 = self.p.get_run(run1["id"])
        self.assertEqual(run1["status"], "draft")
        self.assertIsNone(run1["journal_id"])
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("0.00"))
        with self.assertRaises(PeriodNotOpen):  # nor can a run be scheduled into a closed period
            self.p.schedule_run(self.a["id"], "P1", "owner")
        # a run's own period governs: it cannot be redirected to a different period at execution
        run2 = self.p.schedule_run(self.a["id"], "P2", "owner")
        with self.assertRaises(AssetError):
            self.c.approve_and_execute("asset.post_depreciation", run2["id"], period_id="P0")
        self.assertEqual(self.c.approve_and_execute("asset.post_depreciation", run2["id"]).result["period_id"], "P2")
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_depreciation_approval_goes_stale_when_asset_is_edited(self):
        run1 = self.p.schedule_run(self.a["id"], "P1", "owner")
        ap = self.c.request_approval("asset.post_depreciation", run1["id"])
        self.c.approve(ap["id"])
        self.assertEqual(ap["manifest"]["amounts"], {"amount": "1000.00"})
        self.assertEqual(ap["manifest"]["bindings"]["asset_version"], 1)
        self.assertEqual(ap["manifest"]["bindings"]["period_id"], "P1")
        self.assertEqual(ap["manifest"]["bindings"]["charge_month"], "2026-10")
        edited = self.p.update_asset(self.a["id"], "owner", salvage_value="1200")
        self.assertEqual(edited["version"], 2)
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        stale_run = self.p.get_run(run1["id"])
        self.assertEqual(stale_run["status"], "cancelled")  # its amount derived from the old parameters
        self.assertTrue(stale_run["stale"])
        self.assertIsNone(stale_run["journal_id"])
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("0.00"))
        fresh = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.assertEqual(fresh["amount"], "900.00")
        self.assertEqual(fresh["replaced_run_id"], run1["id"])
        self.c.approve_and_execute("asset.post_depreciation", fresh["id"], period_id="P1")
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("900.00"))
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class OverDepreciationGuardTests(unittest.TestCase):
    """The register can never exceed cost - salvage, whatever the period rows look like."""

    def setUp(self):
        self.f = Fixture()
        self.c = self.f.c
        self.p = self.f.assets
        self.a = self.f.capitalized(description="Laser level", cost="1000", useful_life_months=3)
        self.c.open_period("P3", "December 2026", "2026-12-01", "2026-12-31")
        self.c.open_period("P4", "January 2027", "2027-01-01", "2027-01-31")

    def post(self, period_id):
        run = self.p.schedule_run(self.a["id"], period_id, "owner")
        self.c.approve_and_execute("asset.post_depreciation", run["id"], period_id=period_id)
        return self.p.get_run(run["id"])

    def test_several_period_rows_in_one_month_charge_the_month_once(self):
        # several open period rows all covering October 2026 (an adjustment period, a split month)
        self.c.open_period("P1b", "October 2026 adjustments", "2026-10-01", "2026-10-31")
        self.c.open_period("P1c", "October 2026 second half", "2026-10-16", "2026-10-31")
        first = self.post("P1")
        self.assertEqual((first["sequence"], first["amount"], first["charge_month"]), (1, "333.33", "2026-10"))
        for pid in ("P1b", "P1c"):
            with self.assertRaises(AssetError) as ctx:
                self.p.schedule_run(self.a["id"], pid, "owner")
            self.assertIn("2026-10", str(ctx.exception))
            self.assertIn("P1", str(ctx.exception))
        a = self.p.get_asset(self.a["id"])
        self.assertEqual(a["accumulated_depreciation"], "333.33")
        self.assertEqual(len(a["runs"]), 1)
        self.assertEqual(self.p.state(self.f.project["id"])["ledger"]["accumulated_depreciation"], "333.33")
        # the remaining months complete the schedule exactly and nothing more can ever post
        self.assertEqual(self.post("P2")["amount"], "333.33")
        self.assertEqual(self.post("P3")["amount"], "333.34")
        a = self.p.get_asset(self.a["id"])
        self.assertEqual((a["accumulated_depreciation"], a["net_book_value"], a["remaining_depreciable"]), ("1000.00", "0.00", "0.00"))
        self.assertTrue(a["fully_depreciated"])
        self.assertFalse(a["over_depreciated"])
        late = self.p.schedule_run(self.a["id"], "P4", "owner")
        self.assertEqual((late["status"], late["amount"]), ("no_charge", "0.00"))
        self.assertIn("fully depreciated", late["note"])
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("1000.00"))
        st = self.p.state(self.f.project["id"])
        self.assertTrue(st["reconciled"])
        # and the asset can still be derecognized with a balanced journal
        r = self.c.approve_and_execute("asset.dispose", self.a["id"], period_id="P4")
        j = self.c.ledger.journal(r.result["journal_id"])
        self.assertEqual([(l["account_code"], l["debit"], l["credit"]) for l in j["lines"]], [("1590", "1000.00", "0.00"), ("1500", "0.00", "1000.00")])
        self.assertEqual(self.c.ledger.balance("1500"), Decimal("0.00"))
        self.assertEqual(accumulated(self.c), Decimal("0.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_replacement_run_may_use_an_adjustment_period_of_the_same_month(self):
        first = self.post("P1")
        self.c.close_period("P1")
        self.c.open_period("P1adj", "October 2026 adjustments", "2026-10-01", "2026-10-31")
        with self.assertRaises(AssetError):  # October is already charged, whichever period row is used
            self.p.schedule_run(self.a["id"], "P1adj", "owner")
        rev = self.c.approve_and_execute("asset.reverse_depreciation", first["id"], period_id="P1adj")
        self.assertEqual(self.c.ledger.journal(rev.result["reversal_journal_id"])["period_id"], "P1adj")
        self.assertEqual(accumulated(self.c), Decimal("0.00"))
        with self.assertRaises(PeriodNotOpen):  # the closed period row stays closed
            self.p.schedule_run(self.a["id"], "P1", "owner")
        replacement = self.p.schedule_run(self.a["id"], "P1adj", "owner")
        self.assertEqual(replacement["replaced_run_id"], first["id"])  # linked by month, not by period id
        self.assertEqual((replacement["sequence"], replacement["amount"], replacement["charge_month"], replacement["status"]), (1, "333.33", "2026-10", "draft"))
        self.c.approve_and_execute("asset.post_depreciation", replacement["id"], period_id="P1adj")
        self.assertEqual(accumulated(self.c), Decimal("333.33"))
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("333.33"))
        self.assertEqual([r["status"] for r in self.p.get_asset(self.a["id"])["runs"]], ["reversed", "posted"])
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_tampered_draft_cannot_post_past_the_depreciable_base(self):
        self.post("P1")
        self.post("P2")
        draft = self.p.schedule_run(self.a["id"], "P3", "owner")
        self.assertEqual(draft["amount"], "333.34")
        # a draft is the only mutable run state; alter it behind the module's back
        self.c.db.execute("UPDATE asset_depreciation_runs SET amount='333.35' WHERE id=?", (draft["id"],))
        with self.assertRaises(AssetError) as ctx:
            self.c.approve_and_execute("asset.post_depreciation", draft["id"], period_id="P3")
        self.assertIn("over-depreciate", str(ctx.exception))
        run = self.p.get_run(draft["id"])
        self.assertEqual(run["status"], "draft")
        self.assertIsNone(run["journal_id"])
        self.assertEqual(accumulated(self.c), Decimal("666.66"))
        self.assertEqual(self.p.get_asset(self.a["id"])["accumulated_depreciation"], "666.66")
        self.assertFalse(self.p.get_asset(self.a["id"])["over_depreciated"])
        self.p.cancel_run(draft["id"], "owner", reason="tampered")
        self.assertEqual(self.post("P3")["amount"], "333.34")
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_charge_is_clamped_to_the_remaining_base(self):
        draft = self.p.schedule_run(self.a["id"], "P1", "owner")
        self.c.db.execute("UPDATE asset_depreciation_runs SET amount='600.00' WHERE id=?", (draft["id"],))  # within the base, so it posts
        self.c.approve_and_execute("asset.post_depreciation", draft["id"], period_id="P1")
        self.assertEqual(accumulated(self.c), Decimal("600.00"))
        self.assertEqual(self.post("P2")["amount"], "333.33")  # 933.33 posted, 66.67 left
        last = self.p.schedule_run(self.a["id"], "P3", "owner")
        self.assertEqual((last["status"], last["amount"]), ("draft", "66.67"))
        self.assertIn("clamped", last["note"])
        self.c.approve_and_execute("asset.post_depreciation", last["id"], period_id="P3")
        a = self.p.get_asset(self.a["id"])
        self.assertEqual((a["accumulated_depreciation"], a["remaining_depreciable"], a["fully_depreciated"], a["over_depreciated"]), ("1000.00", "0.00", True, False))
        self.assertEqual(self.p.schedule_run(self.a["id"], "P4", "owner")["status"], "no_charge")
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))
        self.assertTrue(self.p.state(self.f.project["id"])["reconciled"])
        r = self.c.approve_and_execute("asset.dispose", self.a["id"], period_id="P4")
        self.assertEqual(r.result["net_book_value"], "0.00")
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_skipped_month_is_not_caught_up_after_the_schedule_ends(self):
        self.post("P1")
        self.post("P3")  # November was never scheduled
        late = self.p.schedule_run(self.a["id"], "P4", "owner")
        self.assertEqual((late["status"], late["amount"], late["sequence"]), ("no_charge", "0.00", 4))
        self.assertIn("333.33 remains", late["note"])
        self.assertEqual(self.p.get_asset(self.a["id"])["remaining_depreciable"], "333.33")
        self.assertEqual(self.post("P2")["amount"], "333.33")  # the missed month itself still carries its charge
        self.assertTrue(self.p.get_asset(self.a["id"])["fully_depreciated"])
        self.assertEqual(accumulated(self.c), Decimal("1000.00"))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.c = self.f.c
        self.p = self.f.assets

    def test_update_rules(self):
        a = self.f.capitalized()
        run0 = self.p.schedule_run(a["id"], "P0", "owner")
        run1 = self.p.schedule_run(a["id"], "P1", "owner")
        with self.assertRaises(AssetError):
            self.p.update_asset(a["id"], "owner", color="orange")
        with self.assertRaises(AssetError):
            self.p.update_asset(a["id"], "owner")
        with self.assertRaises(AssetError):  # cost is frozen once capitalized
            self.p.update_asset(a["id"], "owner", cost="13000")
        with self.assertRaises(AssetError):  # validation applies to edits too
            self.p.update_asset(a["id"], "owner", useful_life_months=0)
        self.assertEqual(self.p.get_asset(a["id"])["version"], 1)
        same = self.p.update_asset(a["id"], "owner", description="Trench box")  # no-op edit does not bump
        self.assertEqual(same["version"], 1)
        edited = self.p.update_asset(a["id"], "owner", useful_life_months=24)
        self.assertEqual(edited["version"], 2)
        self.assertEqual(edited["monthly_amount"], "500.00")
        self.assertEqual({r["id"]: r["status"] for r in edited["runs"]}, {run0["id"]: "cancelled", run1["id"]: "cancelled"})
        self.assertEqual(self.p.schedule_run(a["id"], "P1", "owner")["amount"], "500.00")
        self.assertEqual(self.p.schedule_run(a["id"], "P0", "owner")["status"], "no_charge")
        actions = [e["action"] for e in self.c.audit.entries(entity_type="asset", entity_id=a["id"])]
        self.assertEqual(actions.count("asset.updated"), 1)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_update_blocked_by_posted_depreciation_and_disposal(self):
        a = self.f.capitalized()
        run1 = self.p.schedule_run(a["id"], "P1", "owner")
        self.c.approve_and_execute("asset.post_depreciation", run1["id"], period_id="P1")
        with self.assertRaises(AssetError):
            self.p.update_asset(a["id"], "owner", useful_life_months=24)
        self.c.approve_and_execute("asset.reverse_depreciation", run1["id"], period_id="P1")
        self.assertEqual(self.p.update_asset(a["id"], "owner", useful_life_months=24)["version"], 2)
        self.c.approve_and_execute("asset.dispose", a["id"], period_id="P1")
        with self.assertRaises(AssetError):
            self.p.update_asset(a["id"], "owner", description="Gone")
        with self.assertRaises(AssetError):
            self.p.update_asset(a["id"], "owner", cost="1")
        b = self.f.register(description="Pump")
        self.assertEqual(self.p.update_asset(b["id"], "owner", cost="1500")["cost"], "1500.00")  # registered assets may still change cost
        renamed = self.p.update_asset(b["id"], "owner", description="Trench box")  # the disposed asset no longer holds the name
        self.assertEqual((renamed["description"], renamed["version"]), ("Trench box", 3))
        c2 = self.f.register(description="Generator")
        with self.assertRaises(AssetError):  # renaming onto another live asset's description is a duplicate
            self.p.update_asset(c2["id"], "owner", description="trench BOX")
        self.assertEqual(self.p.get_asset(c2["id"])["version"], 1)


class DisposalTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.c = self.f.c
        self.p = self.f.assets

    def test_dispose_after_one_run_expenses_book_value(self):
        a = self.f.capitalized()
        run1 = self.p.schedule_run(a["id"], "P1", "owner")
        self.c.approve_and_execute("asset.post_depreciation", run1["id"], period_id="P1")
        ap = self.c.request_approval("asset.dispose", a["id"])
        self.assertEqual(ap["manifest"]["amounts"], {"cost": "12000.00", "accumulated_depreciation": "1000.00", "net_book_value": "11000.00"})
        self.c.approve(ap["id"])
        r = self.c.execute(ap["id"], period_id="P1")
        self.assertEqual(r.result["status"], "disposed")
        self.assertEqual(r.result["accumulated_depreciation"], "1000.00")
        self.assertEqual(r.result["net_book_value"], "11000.00")
        j = self.c.ledger.journal(r.result["journal_id"])
        self.assertEqual(
            [(l["account_code"], l["debit"], l["credit"]) for l in j["lines"]],
            [("1590", "1000.00", "0.00"), ("5200", "11000.00", "0.00"), ("1500", "0.00", "12000.00")],
        )
        self.assertEqual(self.c.ledger.balance("1500"), Decimal("0.00"))
        self.assertEqual(accumulated(self.c), Decimal("0.00"))
        self.assertEqual(self.c.ledger.balance("5200"), Decimal("12000.00"))
        self.assertEqual(self.c.ledger.balance("1000"), Decimal("-12000.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        a = self.p.get_asset(a["id"])
        self.assertEqual(a["status"], "disposed")
        self.assertEqual(a["disposal_journal_id"], j["id"])
        self.assertEqual(a["net_book_value"], "0.00")
        self.assertEqual(a["accumulated_depreciation"], "1000.00")  # history is kept
        for bad in (
            lambda: self.p.schedule_run(a["id"], "P2", "owner"),
            lambda: self.c.approve_and_execute("asset.dispose", a["id"], period_id="P1"),
            lambda: self.c.approve_and_execute("asset.reverse_depreciation", run1["id"], period_id="P1"),
            lambda: self.c.approve_and_execute("asset.capitalise", a["id"], period_id="P1"),
        ):
            with self.assertRaises(AssetError):
                bad()
        with self.assertRaises(sqlite3.IntegrityError):  # disposed rows are immutable at the database level
            self.c.db.execute("UPDATE asset_register SET status='active' WHERE id=?", (a["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("DELETE FROM asset_register WHERE id=?", (a["id"],))
        actions = [e["action"] for e in self.c.audit.entries(entity_type="asset", entity_id=a["id"])]
        self.assertEqual(actions, ["asset.registered", "asset.capitalised", "asset.disposed"])
        run_actions = [e["action"] for e in self.c.audit.entries(entity_type="asset_run", entity_id=run1["id"])]
        self.assertEqual(run_actions, ["asset.run_scheduled", "asset.depreciation_posted"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_disposal_cannot_be_dated_before_the_assets_journals(self):
        # capitalized in October (P1): never derecognized in September (P0)
        a = self.f.capitalized()
        ap = self.c.request_approval("asset.dispose", a["id"])
        self.assertIn("2026-10-01", ap["manifest"]["bindings"]["target_rule"])
        self.c.approve(ap["id"])
        with self.assertRaises(AssetError) as ctx:
            self.c.execute(ap["id"], period_id="P0")
        self.assertIn("cannot be dated before", str(ctx.exception))
        self.assertEqual(self.p.get_asset(a["id"])["status"], "active")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        # nor before its latest depreciation journal: an October run reversed in November
        b = self.f.capitalized(description="Plate compactor")
        run1 = self.p.schedule_run(b["id"], "P1", "owner")
        self.c.approve_and_execute("asset.post_depreciation", run1["id"], period_id="P1")
        self.c.approve_and_execute("asset.reverse_depreciation", run1["id"], period_id="P2")
        for early in ("P0", "P1"):
            with self.assertRaises(AssetError):
                self.c.approve_and_execute("asset.dispose", b["id"], period_id=early)
        self.assertEqual(self.c.ledger.journals(period_id="P0"), [])
        self.assertEqual(self.c.ledger.balance("1500"), Decimal("24000.00"))
        r = self.c.approve_and_execute("asset.dispose", b["id"], period_id="P2")
        self.assertEqual((r.result["status"], r.result["period_id"], r.result["net_book_value"]), ("disposed", "P2", "12000.00"))
        r = self.c.execute(ap["id"], period_id="P1")  # the first asset's own month is fine
        self.assertEqual((r.result["status"], r.result["period_id"]), ("disposed", "P1"))
        self.assertEqual(self.c.ledger.balance("1500"), Decimal("0.00"))
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_dispose_requires_active_asset_without_open_drafts(self):
        registered = self.f.register(description="Unbought")
        with self.assertRaises(AssetError):
            self.c.approve_and_execute("asset.dispose", registered["id"], period_id="P1")
        a = self.f.capitalized()
        draft = self.p.schedule_run(a["id"], "P1", "owner")
        with self.assertRaises(AssetError):
            self.c.approve_and_execute("asset.dispose", a["id"], period_id="P1")
        self.assertEqual(self.p.get_asset(a["id"])["status"], "active")
        self.p.cancel_run(draft["id"], "owner", reason="disposing instead")
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.approve_and_execute("asset.dispose", a["id"], period_id="P1")
        r = self.c.approve_and_execute("asset.dispose", a["id"], period_id="P2")
        self.assertEqual(r.result["accumulated_depreciation"], "0.00")
        self.assertEqual(r.result["net_book_value"], "12000.00")
        j = self.c.ledger.journal(r.result["journal_id"])
        self.assertEqual([(l["account_code"], l["debit"], l["credit"]) for l in j["lines"]], [("5200", "12000.00", "0.00"), ("1500", "0.00", "12000.00")])
        self.assertEqual(j["period_id"], "P2")
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])


class StateTests(unittest.TestCase):
    def test_state_shape_and_reconciliation(self):
        f = Fixture()
        c, p = f.c, f.assets
        self.assertEqual(p.state(f.project["id"]), {
            "assets": [], "totals": {"cost": "0.00", "accumulated_depreciation": "0.00", "net_book_value": "0.00", "registered": 0, "active": 0, "disposed": 0},
            "ledger": {"fixed_assets": "0.00", "accumulated_depreciation": "0.00"}, "reconciled": True, "posting_rule": "cipher-posting-rules/1",
        })
        a = f.capitalized()
        b = f.capitalized(description="Laser level", cost="1000", useful_life_months=3)
        pending = f.register(description="Pending purchase", cost="500", useful_life_months=5)
        other_project = c.create_project(name="Other", entity="E", budget="1")
        f.capitalized(project_id=other_project["id"], description="Elsewhere", cost="700", useful_life_months=7)
        for asset in (a, b):
            run = p.schedule_run(asset["id"], "P1", "owner")
            c.approve_and_execute("asset.post_depreciation", run["id"], period_id="P1")
        p.schedule_run(b["id"], "P0", "owner")
        st = p.state(f.project["id"])
        self.assertEqual([x["description"] for x in st["assets"]], ["Trench box", "Laser level", "Pending purchase"])
        self.assertEqual(st["totals"], {"cost": "13000.00", "accumulated_depreciation": "1333.33", "net_book_value": "11666.67", "registered": 1, "active": 2, "disposed": 0})
        self.assertEqual(st["ledger"], {"fixed_assets": "13000.00", "accumulated_depreciation": "1333.33"})
        self.assertTrue(st["reconciled"])
        laser = st["assets"][1]
        self.assertEqual(laser["net_book_value"], "666.67")
        self.assertEqual(sorted(r["status"] for r in laser["runs"]), ["no_charge", "posted"])
        self.assertEqual(st["assets"][2]["status"], "registered")
        c.approve_and_execute("asset.dispose", a["id"], period_id="P1")
        st = p.state(f.project["id"])
        self.assertEqual(st["totals"]["cost"], "1000.00")
        self.assertEqual(st["totals"]["disposed"], 1)
        self.assertEqual(st["ledger"], {"fixed_assets": "1000.00", "accumulated_depreciation": "333.33"})
        self.assertTrue(st["reconciled"])
        full = c.project_state(f.project["id"])
        self.assertEqual(full["asset"]["totals"], st["totals"])
        self.assertTrue(full["trial_balance"]["balanced"])
        self.assertTrue(full["audit_chain"]["ok"])
        self.assertEqual(p.state(other_project["id"])["totals"]["cost"], "700.00")

    def test_unknown_operation_and_subjects_are_rejected(self):
        f = Fixture()
        with self.assertRaises(AssetError):
            f.assets.manifest_for("asset.melt", "ast_x", actor_role="owner")
        with self.assertRaises(AssetError):
            f.c.request_approval("asset.capitalise", "ast_missing")
        with self.assertRaises(AssetError):
            f.c.request_approval("asset.post_depreciation", "dep_missing")
        with self.assertRaises(AssetError):
            f.assets.get_run("dep_missing")
        self.assertEqual(f.c.approvals.list(), [])


if __name__ == "__main__":
    unittest.main()
