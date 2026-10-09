"""Canonical cents for signed reviews, fingerprints and confirmation hashes.

Reuse the existing cent rounding; no pricing formulas or ORM types change here.
Public response models continue to serialize money as JSON numbers.
"""

from decimal import Decimal

from app.services.booking_service import MAX_MONEY, _money


def canonical_money(value: Decimal | int | float) -> str:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float)):
        raise ValueError("Money must be a finite numeric value")
    amount = Decimal(str(value))
    if not amount.is_finite() or abs(amount) > MAX_MONEY:
        raise ValueError("Money is outside the supported range")
    cents = _money(amount)
    return "0.00" if cents == 0 else format(cents, ".2f")
