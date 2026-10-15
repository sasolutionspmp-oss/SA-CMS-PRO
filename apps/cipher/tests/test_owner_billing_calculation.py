"""Pure owner pay-app arithmetic; no adoption, approval or posting authority."""
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import unittest

from apps.cipher.domain.owner_billing_calculation import (
    OwnerBillingCalculationError, OwnerProgressLine, OwnerSOVLine, calculate_owner_pay_app,
)


def example():
    sov = (
        OwnerSOVLine("U1", "Installed sheet piles", "unitPrice", 10_000_000,
                     unit="EA", contract_quantity="100", unit_price_cents=100_000),
        OwnerSOVLine("L2", "Dewatering lump sum", "lumpSum", 15_000_000),
    )
    progress = (
        OwnerProgressLine("U1", "20", "35", "30", "Five claimed piles were not verified installed."),
        OwnerProgressLine("L2", "30000", "60000", "50000", "The reviewed progress excludes unperformed testing."),
    )
    return sov, progress


def calculate(sov=None, progress=None, **kwargs):
    original_sov, original_progress = example()
    return calculate_owner_pay_app(
        sov_lines=original_sov if sov is None else sov,
        progress_lines=original_progress if progress is None else progress,
        prime_contract_value_cents=kwargs.pop("prime_contract_value_cents", 25_000_000),
        prior_retained_cents=kwargs.pop("prior_retained_cents", 500_000),
        retainage_released_cents=kwargs.pop("retainage_released_cents", 0),
        retainage_rate=kwargs.pop("retainage_rate", "0.10"),
        **kwargs,
    )


class OwnerBillingCalculationTests(unittest.TestCase):
    def test_claimed_reviewed_and_prior_amounts_produce_exact_separate_ar_and_retainage(self):
        result = calculate()
        self.assertEqual(result.prior_certified_cents, 5_000_000)
        self.assertEqual(result.claimed_certified_cents, 9_500_000)
        self.assertEqual(result.reviewed_certified_cents, 8_000_000)
        self.assertEqual(result.revenue_this_period_cents, 3_000_000)
        self.assertEqual(result.retained_cumulative_cents, 800_000)
        self.assertEqual(result.retainage_this_period_cents, 300_000)
        self.assertEqual(result.amount_due_cents, 2_700_000)
        self.assertEqual(
            [(line.account_code, line.debit_cents, line.credit_cents) for line in result.journal_preview],
            [("1100", 2_700_000, 0), ("1150", 300_000, 0), ("4000", 0, 3_000_000)],
        )
        self.assertEqual(result.lines[0].reviewed_quantity, "30")
        self.assertEqual(result.lines[0].reviewed_amount_cents, 3_000_000)
        self.assertIsNone(result.lines[1].reviewed_quantity)
        self.assertEqual(result.lines[1].reviewed_amount_cents, 5_000_000)
        self.assertEqual(sum(line.this_period_cents for line in result.lines), 3_000_000)

    def test_rounds_cumulative_unit_values_before_subtracting_previous_value(self):
        # Rounding the 0.02 quantity increment would lose the actual one-cent change.
        sov = (OwnerSOVLine("U", "Measured sample", "unitPrice", 3,
                            unit="EA", contract_quantity="3", unit_price_cents=1),)
        progress = (OwnerProgressLine("U", "0.49", "0.51", "0.51"),)
        result = calculate(sov, progress, prime_contract_value_cents=3,
                           prior_retained_cents=0, retainage_rate="0")
        self.assertEqual((result.prior_certified_cents, result.reviewed_certified_cents,
                          result.revenue_this_period_cents, result.amount_due_cents), (0, 1, 1, 1))

    def test_half_cent_rounds_up_once_per_line(self):
        sov = (OwnerSOVLine("U", "Measured sample", "unitPrice", 3,
                            unit="EA", contract_quantity="3", unit_price_cents=1),)
        progress = (OwnerProgressLine("U", "0", "0.5", "0.5"),)
        result = calculate(sov, progress, prime_contract_value_cents=3,
                           prior_retained_cents=0, retainage_rate="0")
        self.assertEqual(result.reviewed_certified_cents, 1)

    def test_retainage_step_down_can_bill_without_recognizing_new_revenue(self):
        sov = (OwnerSOVLine("L", "Complete scope", "lumpSum", 20_000_000),)
        progress = (OwnerProgressLine("L", "100000", "100000", "100000"),)
        result = calculate(sov, progress, prime_contract_value_cents=20_000_000,
                           prior_retained_cents=1_000_000, retainage_rate="0.05")
        self.assertEqual((result.revenue_this_period_cents, result.retainage_this_period_cents,
                          result.amount_due_cents), (0, -500_000, 500_000))
        self.assertEqual([(line.account_code, line.debit_cents, line.credit_cents)
                          for line in result.journal_preview], [("1100", 500_000, 0), ("1150", 0, 500_000)])

    def test_does_not_reduce_retained_below_amount_already_released(self):
        sov = (OwnerSOVLine("L", "Complete scope", "lumpSum", 20_000_000),)
        progress = (OwnerProgressLine("L", "100000", "100000", "100000"),)
        with self.assertRaises(OwnerBillingCalculationError):
            calculate(sov, progress, prime_contract_value_cents=20_000_000,
                      prior_retained_cents=1_000_000, retainage_released_cents=750_000,
                      retainage_rate="0.05")

    def test_any_review_difference_requires_a_reason_even_when_cent_amount_is_equal(self):
        sov, progress = example()
        for index in (0, 1):
            with self.subTest(index=index), self.assertRaises(OwnerBillingCalculationError):
                altered = list(progress)
                altered[index] = replace(altered[index], difference_reason=" ")
                calculate(sov, altered)
        small = (OwnerSOVLine("U", "Measured sample", "unitPrice", 3,
                              unit="EA", contract_quantity="3", unit_price_cents=1),
                 OwnerSOVLine("L", "Other work", "lumpSum", 100))
        small_progress = (OwnerProgressLine("U", "0", "0.51", "0.52"),
                          OwnerProgressLine("L", "0", "1", "1"))
        with self.assertRaises(OwnerBillingCalculationError):
            calculate(small, small_progress, prime_contract_value_cents=103,
                      prior_retained_cents=0, retainage_rate="0")

    def test_unit_quantity_and_lump_sum_amount_caps_are_independent(self):
        sov, progress = example()
        for index, value in ((0, "100.000001"), (1, "150000.01")):
            altered = list(progress)
            altered[index] = replace(altered[index], claimed_cumulative=value,
                                     reviewed_cumulative=value, difference_reason="")
            with self.subTest(index=index), self.assertRaises(OwnerBillingCalculationError):
                calculate(sov, altered)

    def test_claimed_and_reviewed_progress_cannot_decrease_previous_certified_source(self):
        sov, progress = example()
        for field in ("claimed_cumulative", "reviewed_cumulative"):
            with self.subTest(field=field), self.assertRaises(OwnerBillingCalculationError):
                calculate(sov, (replace(progress[0], **{field: "19.999999"}), progress[1]))

    def test_requires_every_sov_line_once_including_zero_value_lines(self):
        sov, progress = example()
        zero = OwnerSOVLine("Z", "Included mobilization", "lumpSum", 0)
        with self.assertRaises(OwnerBillingCalculationError):
            calculate((*sov, zero), progress)
        result = calculate((*sov, zero), (*progress, OwnerProgressLine("Z", "0", "0", "0")))
        self.assertEqual(result.lines[-1].reviewed_amount_cents, 0)
        for altered in (progress[:1], (*progress, progress[0]),
                        (*progress, OwnerProgressLine("other", "0", "0", "0"))):
            with self.subTest(altered=altered), self.assertRaises(OwnerBillingCalculationError):
                calculate(sov, altered)

    def test_sov_total_must_equal_the_explicit_owner_contract_amount(self):
        for amount in (24_999_999, 25_000_001):
            with self.subTest(amount=amount), self.assertRaises(OwnerBillingCalculationError):
                calculate(prime_contract_value_cents=amount)

    def test_unit_price_scheduled_value_must_match_quantity_and_rate(self):
        sov, progress = example()
        with self.assertRaises(OwnerBillingCalculationError):
            calculate((replace(sov[0], scheduled_amount_cents=10_000_001), sov[1]), progress,
                      prime_contract_value_cents=25_000_001)

    def test_rejects_python_boolean_and_float_aliases_for_integer_cents(self):
        for value in (True, False, 25_000_000.0, "25000000"):
            with self.subTest(value=value), self.assertRaises(OwnerBillingCalculationError):
                calculate(prime_contract_value_cents=value)
        for field in ("prior_retained_cents", "retainage_released_cents"):
            for value in (False, 0.0):
                with self.subTest(field=field, value=value), self.assertRaises(OwnerBillingCalculationError):
                    calculate(**{field: value})
        sov, progress = example()
        for value in (False, 0.0):
            with self.subTest(value=value), self.assertRaises(OwnerBillingCalculationError):
                calculate((replace(sov[0], unit_price_cents=value), sov[1]), progress)

    def test_quantity_and_money_inputs_use_exact_bounded_decimal_strings(self):
        sov, progress = example()
        for value in (30, 30.0, True, " 30", "3e1", "+30", "030", "NaN", "Infinity", "30.0000001", "-1"):
            with self.subTest(value=value), self.assertRaises(OwnerBillingCalculationError):
                calculate(sov, (replace(progress[0], reviewed_cumulative=value), progress[1]))
        for value in ("50000.001", 50000.0):
            with self.subTest(value=value), self.assertRaises(OwnerBillingCalculationError):
                calculate(sov, (progress[0], replace(progress[1], reviewed_cumulative=value)))
        for value in ("1.000001", "-0.1", "1e-1", 0.1, True):
            with self.subTest(value=value), self.assertRaises(OwnerBillingCalculationError):
                calculate(retainage_rate=value)

    def test_invalid_source_shapes_and_unbounded_work_are_refused(self):
        sov, progress = example()
        for altered in ((), (sov[0], sov[0]), (replace(sov[0], basis="percent"), sov[1]),
                        (replace(sov[0], unit=""), sov[1]),
                        (replace(sov[1], unit="EA"), sov[0]),
                        (replace(sov[0], scheduled_amount_cents=10**16), sov[1])):
            with self.subTest(altered=altered), self.assertRaises(OwnerBillingCalculationError):
                calculate(altered, progress)
        with self.assertRaises(OwnerBillingCalculationError):
            calculate(sov * 51, progress * 51)

    def test_retainage_source_facts_must_be_possible_and_never_create_a_negative_invoice(self):
        for kwargs in ({"prior_retained_cents": 5_000_001},
                       {"retainage_released_cents": 500_001},
                       {"retainage_rate": "1"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(OwnerBillingCalculationError):
                calculate(**kwargs)

    def test_unchanged_work_and_retainage_produce_no_new_bill(self):
        sov, progress = example()
        unchanged = tuple(replace(line, claimed_cumulative=line.previous_cumulative,
                                  reviewed_cumulative=line.previous_cumulative, difference_reason="") for line in progress)
        with self.assertRaises(OwnerBillingCalculationError):
            calculate(sov, unchanged)

    def test_normalized_calculation_hash_binds_review_reason_and_preserves_input_order(self):
        sov, progress = example()
        original = calculate(sov, progress)
        normalized = calculate((replace(sov[0], contract_quantity="100.000000"), sov[1]),
                               (replace(progress[0], previous_cumulative="20.0", claimed_cumulative="35.00",
                                        reviewed_cumulative="30.000000"), progress[1]), retainage_rate="0.100000")
        self.assertEqual(original.calculation_hash, normalized.calculation_hash)
        changed_reason = calculate(sov, (replace(progress[0], difference_reason="A different documented review."), progress[1]))
        self.assertNotEqual(original.calculation_hash, changed_reason.calculation_hash)
        self.assertEqual([line.line_id for line in original.lines], ["U1", "L2"])
        with self.assertRaises(FrozenInstanceError):
            original.amount_due_cents = 1
        serialized = original.as_dict()
        serialized["lines"][0]["reviewedAmountCents"] = 1
        self.assertEqual(original.lines[0].reviewed_amount_cents, 3_000_000)

    def test_calculation_composes_with_genuine_existing_cumulative_receivables_journals(self):
        from apps.cipher.tests.test_receivables_controls import World

        cases = (
            ("ordinary progress", "0.10", "0.10", "50000", "80000", 500_000),
            ("retainage step-down", "0.10", "0.05", "100000", "100000", 1_000_000),
            ("fully retained first progress", "1", "1", "0", "1", 0),
        )
        for label, prior_rate, current_rate, previous, reviewed, previous_retained in cases:
            with self.subTest(case=label):
                world = World(contract="250000", rate=prior_rate)
                try:
                    if Decimal(previous):
                        world.posted(previous, invoice_date="2026-10-01")
                    if prior_rate != current_rate:
                        world.r.set_prime_contract(world.pid, "250000", current_rate, actor="owner")
                    source_sov = (OwnerSOVLine("L", "Explicit synthetic owner scope", "lumpSum", 25_000_000),)
                    source_progress = (OwnerProgressLine("L", previous, reviewed, reviewed),)
                    before = "\n".join(world.c.db.conn.iterdump())
                    result = calculate(source_sov, source_progress, prior_retained_cents=previous_retained,
                                       retainage_rate=current_rate)
                    self.assertEqual("\n".join(world.c.db.conn.iterdump()), before)
                    bill = world.posted(reviewed, invoice_date="2026-10-01")
                    self.assertEqual(int(Decimal(bill["amount_due"]) * 100), result.amount_due_cents)
                    self.assertEqual(int(Decimal(bill["revenue_this_period"]) * 100), result.revenue_this_period_cents)
                    journal = world.c.ledger.journal(bill["journal_id"])
                    self.assertEqual(
                        [(row["account_code"], int(Decimal(row["debit"]) * 100), int(Decimal(row["credit"]) * 100))
                         for row in journal["lines"]],
                        [(row.account_code, row.debit_cents, row.credit_cents) for row in result.journal_preview],
                    )
                    world.assert_books(self)
                finally:
                    world.c.db.close()


if __name__ == "__main__":
    unittest.main()
