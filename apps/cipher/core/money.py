"""Exact decimal money.

All monetary values inside Cipher are ``decimal.Decimal`` quantised to cents
and are stored in SQLite as canonical strings.  Binary floating point is
rejected at the boundary so that a float can never enter the books, and so are
non-finite values (NaN, sNaN, +/-Infinity) and magnitudes at or above
``MAX_ABS`` (10**13), which no amount in a one-entity synthetic ledger can
legitimately reach and which would otherwise lose cents once stored.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from fractions import Fraction
from typing import Iterable, Sequence

getcontext().prec = 28

CENTS = Decimal("0.01")
RATE_PLACES = Decimal("0.000001")
ZERO = Decimal("0.00")
MAX_ABS = Decimal(10) ** 13


class MoneyError(ValueError):
    """Raised when a value cannot be used as exact money."""


def _checked(value: Decimal, original) -> Decimal:
    """Refuse non-finite and out-of-range decimals.  ``is_finite`` is tested first
    because comparing a signalling NaN raises ``InvalidOperation``."""
    if not value.is_finite():
        raise MoneyError(f"non-finite monetary value is not allowed: {original!r}")
    if value.copy_abs() >= MAX_ABS:  # copy_abs is exact; abs() would round to the context precision
        raise MoneyError(f"monetary value out of range (absolute value must be below 10**13): {original!r}")
    return value


def D(value) -> Decimal:
    """Convert ``value`` to a finite, bounded Decimal without rounding.

    Accepts Decimal, int or str.  Floats and bools are rejected because they
    are not exact representations of money; NaN, sNaN, +/-Infinity and values
    whose absolute value is 10**13 or more are rejected with ``MoneyError``.
    """
    if isinstance(value, Decimal):
        return _checked(value, value)
    if isinstance(value, bool):
        raise MoneyError("boolean is not a monetary value")
    if isinstance(value, int):
        return _checked(Decimal(value), value)
    if isinstance(value, float):
        raise MoneyError("binary floating point money is not allowed; pass a str or Decimal")
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            raise MoneyError("empty monetary string")
        try:
            parsed = Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError(f"not a decimal amount: {value!r}") from exc
        return _checked(parsed, value)
    raise MoneyError(f"unsupported monetary type: {type(value).__name__}")


def money(value) -> Decimal:
    """Quantise ``value`` to cents (half-up).  The rounded amount must still be in
    range (9999999999999.995 rounds to 10**13 and is refused)."""
    return _checked(D(value).quantize(CENTS, rounding=ROUND_HALF_UP), value)


def rate(value) -> Decimal:
    """A ratio such as a retainage rate, kept to six places."""
    r = D(value).quantize(RATE_PLACES, rounding=ROUND_HALF_UP)
    if r < 0 or r > 1:
        raise MoneyError(f"rate must be between 0 and 1: {r}")
    return r


def fmt(value) -> str:
    """Canonical string form used for storage and hashing."""
    return f"{money(value):f}"


def total(values: Iterable) -> Decimal:
    acc = ZERO
    for v in values:
        acc += money(v)
    return money(acc)


def pct(amount, ratio) -> Decimal:
    """``amount * ratio`` quantised to cents."""
    return money(D(amount) * D(ratio))


def allocate(amount, weights: Sequence) -> list[Decimal]:
    """Split ``amount`` (quantised to cents) proportionally to ``weights`` with the
    largest-remainder method.

    Each exact share ``|amount| * w / sum(w)`` is computed as an exact fraction and
    rounded toward zero to whole cents; the cents still missing are handed out one
    at a time to the parts with the largest fractional remainders (ties go to the
    larger weight, then to the lower index).  The parts therefore always sum
    exactly to the amount, every part is within one cent of its exact share, and
    no part has the opposite sign of the amount.  Negative weights are rejected.
    When every weight is zero the whole amount goes to the first part.

    No step runs in the 28-digit Decimal context: the weight total is an exact
    ``Fraction`` sum, so weights that differ only beyond 28 significant digits still
    rank their remainders exactly."""
    amt = money(amount)
    ws = [D(w) for w in weights]
    if not ws:
        raise MoneyError("cannot allocate across zero weights")
    if any(w < 0 for w in ws):
        raise MoneyError("negative allocation weight")
    fractions = [Fraction(w) for w in ws]  # exact: a finite Decimal converts without rounding
    denom_f = sum(fractions, Fraction(0))
    if denom_f == 0:
        parts = [ZERO for _ in ws]
        parts[0] = amt
        return parts
    sign = -1 if amt < 0 else 1
    total_cents = int(abs(amt) / CENTS)  # exact: amt is quantised to cents
    exact = [Fraction(total_cents) * f / denom_f for f in fractions]  # each share, in cents
    floors = [int(e) for e in exact]  # toward zero (shares are non-negative)
    remaining = total_cents - sum(floors)
    order = sorted(range(len(ws)), key=lambda i: (-(exact[i] - floors[i]), -fractions[i], i))
    for i in order[:remaining]:
        floors[i] += 1
    return [(Decimal(sign * c) * CENTS).quantize(CENTS) for c in floors]


def assert_non_negative(value, label: str = "amount") -> Decimal:
    m = money(value)
    if m < 0:
        raise MoneyError(f"{label} cannot be negative: {m}")
    return m
