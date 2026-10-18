
"""Tests for cancellation fee calculations."""

from decimal import Decimal

import pytest

from app.services.cancellation_policy import calculate_cancellation_fee


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (100, "20.00"),
        (150, "30.00"),
        (225.50, "45.10"),
        (99.99, "20.00"),
        (0, "0.00"),
    ],
)
def test_cancellation_fee_calculation(total, expected):
    result = calculate_cancellation_fee(total)

    assert result == Decimal(expected)


@pytest.mark.parametrize("total", [-100, float("nan"), float("inf")])
def test_invalid_reservation_total(total):
    with pytest.raises(ValueError):
        calculate_cancellation_fee(total)
