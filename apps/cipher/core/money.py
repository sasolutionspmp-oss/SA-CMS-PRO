"""Exact decimal money.

All monetary values inside Cipher are ``decimal.Decimal`` quantised to cents
and are stored in SQLite as canonical strings.  Binary floating point is
rejected at the boundary so that a float can never enter the books.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from typing import Iterable, Sequence

getcontext().prec = 28

CENTS = Decimal("0.01")
RATE_PLACES = Decimal("0.000001")
ZERO = Decimal("0.00")


class MoneyError(ValueError):
    """Raised when a value cannot be used as exact money."""


def D(value) -> Decimal:
    """Convert ``value`` to a Decimal without rounding.

    Accepts Decimal, int or str.  Floats and bools are rejected because they
    are not exact representations of money.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise MoneyError("boolean is not a monetary value")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise MoneyError("binary floating point money is not allowed; pass a str or Decimal")
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            raise MoneyError("empty monetary string")
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise MoneyError(f"not a decimal amount: {value!r}") from exc
    raise MoneyError(f"unsupported monetary type: {type(value).__name__}")


def money(value) -> Decimal:
    """Quantise ``value`` to cents (half-up)."""
    return D(value).quantize(CENTS, rounding=ROUND_HALF_UP)


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
    """Split ``amount`` proportionally to ``weights`` with the rounding residual
    assigned to the largest weight so that the parts always sum exactly."""
    amt = money(amount)
    ws = [D(w) for w in weights]
    if not ws:
        raise MoneyError("cannot allocate across zero weights")
    if any(w < 0 for w in ws):
        raise MoneyError("negative allocation weight")
    denom = sum(ws)
    if denom == 0:
        parts = [ZERO for _ in ws]
        parts[0] = amt
        return parts
    parts = [money(amt * w / denom) for w in ws]
    residual = amt - sum(parts)
    if residual != 0:
        idx = max(range(len(ws)), key=lambda i: ws[i])
        parts[idx] = money(parts[idx] + residual)
    return parts


def assert_non_negative(value, label: str = "amount") -> Decimal:
    m = money(value)
    if m < 0:
        raise MoneyError(f"{label} cannot be negative: {m}")
    return m
