
"""Cancellation fee calculations for LikeHome."""

from decimal import Decimal, ROUND_HALF_UP

from app.config.constants import Constants


def calculate_cancellation_fee(reservation_total: float | Decimal) -> Decimal:
    """Calculate the cancellation fee using LikeHome's configured policy."""

    total = Decimal(str(reservation_total))
    fee_rate = Decimal(str(Constants.CANCELLATION_FEE))

    if not total.is_finite() or total < 0:
        raise ValueError("Reservation total must be a non-negative finite amount")

    if not fee_rate.is_finite() or not Decimal("0") <= fee_rate <= Decimal("1"):
        raise ValueError("Cancellation fee rate must be between 0 and 1")

    fee = total * fee_rate

    return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
