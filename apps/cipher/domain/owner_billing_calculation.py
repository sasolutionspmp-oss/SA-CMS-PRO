"""Exact, pure claimed-versus-reviewed owner pay-app calculation.

This module deliberately has no database, actor, approval, transport or service
dependency. Its inputs must later come from an audited adopted owner SOV and the
standing prior owner certification; calculating a hash does not establish that
source authority. It cannot adopt a contract, certify work, post or send a bill.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re
from typing import Any, Sequence

from ..core.ids import hash_json


CALCULATION_VERSION = "cipher.owner-billing-calculation.v1"
MAX_LINES = 100
MAX_CENTS = 9_000_000_000_000  # Exact in the bounded JSON/JavaScript integer range.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_QUANTITY = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?\Z")
_DOLLARS = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?\Z")
_RATE = re.compile(r"(?:0|1)(?:\.[0-9]{1,6})?\Z")


class OwnerBillingCalculationError(ValueError):
    """A bounded owner pay app cannot be calculated from these source facts."""


@dataclass(frozen=True)
class OwnerSOVLine:
    line_id: str
    description: str
    basis: str
    scheduled_amount_cents: int
    unit: str | None = None
    contract_quantity: str | None = None
    unit_price_cents: int | None = None


@dataclass(frozen=True)
class OwnerProgressLine:
    line_id: str
    previous_cumulative: str
    claimed_cumulative: str
    reviewed_cumulative: str
    difference_reason: str = ""


@dataclass(frozen=True)
class OwnerCalculatedLine:
    line_id: str
    description: str
    basis: str
    scheduled_amount_cents: int
    unit: str | None
    contract_quantity: str | None
    unit_price_cents: int | None
    previous_quantity: str | None
    claimed_quantity: str | None
    reviewed_quantity: str | None
    previous_amount_cents: int
    claimed_amount_cents: int
    reviewed_amount_cents: int
    this_period_cents: int
    difference_amount_cents: int
    difference_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "lineId": self.line_id, "description": self.description, "basis": self.basis,
            "scheduledAmountCents": self.scheduled_amount_cents, "unit": self.unit,
            "contractQuantity": self.contract_quantity, "unitPriceCents": self.unit_price_cents,
            "previousQuantity": self.previous_quantity, "claimedQuantity": self.claimed_quantity,
            "reviewedQuantity": self.reviewed_quantity, "previousAmountCents": self.previous_amount_cents,
            "claimedAmountCents": self.claimed_amount_cents, "reviewedAmountCents": self.reviewed_amount_cents,
            "thisPeriodCents": self.this_period_cents, "differenceAmountCents": self.difference_amount_cents,
            "differenceReason": self.difference_reason,
        }


@dataclass(frozen=True)
class OwnerJournalPreviewLine:
    account_code: str
    debit_cents: int
    credit_cents: int
    memo: str

    def as_dict(self) -> dict[str, Any]:
        return {"accountCode": self.account_code, "debitCents": self.debit_cents,
                "creditCents": self.credit_cents, "memo": self.memo}


@dataclass(frozen=True)
class OwnerPayAppCalculation:
    lines: tuple[OwnerCalculatedLine, ...]
    prime_contract_value_cents: int
    prior_certified_cents: int
    claimed_certified_cents: int
    reviewed_certified_cents: int
    prior_retained_cents: int
    retainage_released_cents: int
    retainage_rate: str
    retained_cumulative_cents: int
    retainage_this_period_cents: int
    revenue_this_period_cents: int
    amount_due_cents: int
    journal_preview: tuple[OwnerJournalPreviewLine, ...]
    calculation_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "calculationVersion": CALCULATION_VERSION,
            "lines": [line.as_dict() for line in self.lines],
            "primeContractValueCents": self.prime_contract_value_cents,
            "priorCertifiedCents": self.prior_certified_cents,
            "claimedCertifiedCents": self.claimed_certified_cents,
            "reviewedCertifiedCents": self.reviewed_certified_cents,
            "priorRetainedCents": self.prior_retained_cents,
            "retainageReleasedCents": self.retainage_released_cents,
            "retainageRate": self.retainage_rate,
            "retainedCumulativeCents": self.retained_cumulative_cents,
            "retainageThisPeriodCents": self.retainage_this_period_cents,
            "revenueThisPeriodCents": self.revenue_this_period_cents,
            "amountDueCents": self.amount_due_cents,
            "journalPreview": [line.as_dict() for line in self.journal_preview],
            "calculationHash": self.calculation_hash,
        }


def _text(value: Any, label: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or len(value) > maximum or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise OwnerBillingCalculationError(f"{label} must be bounded plain text")
    value = value.strip()
    if not value and not empty:
        raise OwnerBillingCalculationError(f"{label} is required")
    return value


def _line_id(value: Any) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise OwnerBillingCalculationError("A bounded stable line ID is required")
    return value


def _cents(value: Any, label: str, *, positive: bool = False) -> int:
    # bool and float are never integer JSON money, even when Python compares them equal.
    if type(value) is not int or value < (1 if positive else 0) or value > MAX_CENTS:
        raise OwnerBillingCalculationError(f"{label} must be bounded integer cents")
    return value


def _decimal(value: Any, label: str, pattern: re.Pattern[str]) -> Decimal:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise OwnerBillingCalculationError(f"{label} requires an exact bounded decimal string")
    return Decimal(value)


def _canonical_decimal(value: Decimal) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _rounded(value: Decimal, label: str) -> int:
    result = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return _cents(result, label)


def calculate_owner_pay_app(
    *, sov_lines: Sequence[OwnerSOVLine], progress_lines: Sequence[OwnerProgressLine],
    prime_contract_value_cents: int, prior_retained_cents: int,
    retainage_released_cents: int, retainage_rate: str,
) -> OwnerPayAppCalculation:
    """Calculate a bounded, full-SOV cumulative progress application.

    Unit-price measures are decimal quantities; lump-sum measures are decimal
    dollar amounts. Both become integer cents on the server. Prior line amounts
    and retainage are source inputs, not a license to rewrite standing history.
    Every source line is required, including included/zero-value lines. Credits,
    negative invoices and work above the adopted SOV require their own workflow.
    """
    if (not isinstance(sov_lines, (tuple, list)) or not 1 <= len(sov_lines) <= MAX_LINES
            or not isinstance(progress_lines, (tuple, list)) or len(progress_lines) != len(sov_lines)):
        raise OwnerBillingCalculationError("A bounded complete owner SOV and matching progress are required")
    contract_cents = _cents(prime_contract_value_cents, "Prime contract value", positive=True)
    prior_retained = _cents(prior_retained_cents, "Prior retained amount")
    released = _cents(retainage_released_cents, "Released retainage")
    rate = _decimal(retainage_rate, "Retainage rate", _RATE)
    if rate > 1:
        raise OwnerBillingCalculationError("Retainage rate must be between zero and one")
    progress: dict[str, OwnerProgressLine] = {}
    for line in progress_lines:
        if type(line) is not OwnerProgressLine:
            raise OwnerBillingCalculationError("Progress must use typed owner progress lines")
        identifier = _line_id(line.line_id)
        if identifier in progress:
            raise OwnerBillingCalculationError("Progress must include every owner SOV line exactly once")
        progress[identifier] = line

    calculated: list[OwnerCalculatedLine] = []
    identifiers: set[str] = set()
    scheduled_total = 0
    with localcontext() as context:
        context.prec = 60
        for line in sov_lines:
            if type(line) is not OwnerSOVLine:
                raise OwnerBillingCalculationError("SOV must use typed owner SOV lines")
            identifier = _line_id(line.line_id)
            if identifier in identifiers or identifier not in progress:
                raise OwnerBillingCalculationError("The owner SOV and progress must contain the same unique line IDs")
            identifiers.add(identifier)
            description = _text(line.description, "Line description", 240)
            scheduled = _cents(line.scheduled_amount_cents, "Scheduled line amount")
            scheduled_total += scheduled
            entry = progress[identifier]
            reason = _text(entry.difference_reason, "Review difference reason", 1000, empty=True)
            if line.basis == "unitPrice":
                unit = _text(line.unit, "Quantity unit", 32)
                quantity = _decimal(line.contract_quantity, "Contract quantity", _QUANTITY)
                if quantity <= 0:
                    raise OwnerBillingCalculationError("A unit-price contract quantity must be positive")
                price = _cents(line.unit_price_cents, "Unit price")
                if _rounded(quantity * price, "Extended scheduled amount") != scheduled:
                    raise OwnerBillingCalculationError("Scheduled unit-price amount must equal its quantity times unit price")
                previous, claimed, reviewed = (
                    _decimal(value, label, _QUANTITY)
                    for value, label in ((entry.previous_cumulative, "Previous quantity"),
                                         (entry.claimed_cumulative, "Claimed quantity"),
                                         (entry.reviewed_cumulative, "Reviewed quantity"))
                )
                if max(previous, claimed, reviewed) > quantity:
                    raise OwnerBillingCalculationError("Owner progress cannot exceed the adopted contract quantity")
                amounts = tuple(_rounded(value * price, "Cumulative unit-price amount")
                                for value in (previous, claimed, reviewed))
                previous_quantity, claimed_quantity, reviewed_quantity = map(_canonical_decimal, (previous, claimed, reviewed))
                contract_quantity = _canonical_decimal(quantity)
            elif line.basis == "lumpSum":
                if line.unit is not None or line.contract_quantity is not None or line.unit_price_cents is not None:
                    raise OwnerBillingCalculationError("Lump-sum values do not carry quantity or unit-price fields")
                previous, claimed, reviewed = (
                    _decimal(value, label, _DOLLARS)
                    for value, label in ((entry.previous_cumulative, "Previous lump-sum amount"),
                                         (entry.claimed_cumulative, "Claimed lump-sum amount"),
                                         (entry.reviewed_cumulative, "Reviewed lump-sum amount"))
                )
                amounts = tuple(_rounded(value * 100, "Cumulative lump-sum amount")
                                for value in (previous, claimed, reviewed))
                if max(amounts) > scheduled:
                    raise OwnerBillingCalculationError("Owner progress cannot exceed the adopted scheduled line amount")
                unit = contract_quantity = price = None
                previous_quantity = claimed_quantity = reviewed_quantity = None
            else:
                raise OwnerBillingCalculationError("Owner lines must use unitPrice or lumpSum basis")
            if claimed < previous or reviewed < previous:
                raise OwnerBillingCalculationError("Cumulative claimed and reviewed progress cannot reduce certified history")
            if claimed != reviewed and not reason:
                raise OwnerBillingCalculationError("Every claimed-versus-reviewed difference needs a reason")
            prior_amount, claimed_amount, reviewed_amount = amounts
            calculated.append(OwnerCalculatedLine(
                identifier, description, line.basis, scheduled, unit, contract_quantity, price,
                previous_quantity, claimed_quantity, reviewed_quantity,
                prior_amount, claimed_amount, reviewed_amount, reviewed_amount - prior_amount,
                reviewed_amount - claimed_amount, reason,
            ))
        if scheduled_total != contract_cents:
            raise OwnerBillingCalculationError("The full owner SOV must equal the explicit prime contract value")
        prior_certified = sum(line.previous_amount_cents for line in calculated)
        claimed_certified = sum(line.claimed_amount_cents for line in calculated)
        reviewed_certified = sum(line.reviewed_amount_cents for line in calculated)
        if prior_retained > prior_certified or released > prior_retained:
            raise OwnerBillingCalculationError("Retainage source facts exceed the standing certified history")
        retained = _rounded(Decimal(reviewed_certified) * rate, "Cumulative retained amount")
        if retained < released:
            raise OwnerBillingCalculationError("Retainage cannot be reduced below the amount already released")
        revenue = reviewed_certified - prior_certified
        retainage_this = retained - prior_retained
        amount_due = (reviewed_certified - retained) - (prior_certified - prior_retained)
        if amount_due < 0:
            raise OwnerBillingCalculationError("A negative current amount needs a separate owner credit workflow")
        if revenue == 0 and retainage_this == 0 and amount_due == 0:
            raise OwnerBillingCalculationError("Certified progress and retainage are unchanged; there is nothing to bill")

    journal: list[OwnerJournalPreviewLine] = []
    if amount_due:
        journal.append(OwnerJournalPreviewLine("1100", amount_due, 0, "Owner bill amount due"))
    if retainage_this > 0:
        journal.append(OwnerJournalPreviewLine("1150", retainage_this, 0, "Retainage receivable"))
    if revenue:
        journal.append(OwnerJournalPreviewLine("4000", 0, revenue, "Reviewed certified progress; synthetic policy"))
    if retainage_this < 0:
        journal.append(OwnerJournalPreviewLine("1150", 0, -retainage_this, "Retainage reduction"))
    assert sum(line.debit_cents for line in journal) == sum(line.credit_cents for line in journal)
    original = {
        "calculationVersion": CALCULATION_VERSION, "lines": [line.as_dict() for line in calculated],
        "primeContractValueCents": contract_cents, "priorRetainedCents": prior_retained,
        "retainageReleasedCents": released, "retainageRate": _canonical_decimal(rate),
    }
    return OwnerPayAppCalculation(
        tuple(calculated), contract_cents, prior_certified, claimed_certified, reviewed_certified,
        prior_retained, released, _canonical_decimal(rate), retained, retainage_this, revenue, amount_due,
        tuple(journal), hash_json(original),
    )
