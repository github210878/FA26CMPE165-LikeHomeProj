
"""Tests for rewards history API response schemas."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.user_schema import (
    RewardHistoryItem,
    RewardHistoryResponse,
)


def test_reward_history_response_with_transactions():
    response = RewardHistoryResponse(
        reward_points=250,
        history=[
            RewardHistoryItem(
                transaction_id=1,
                points_change=150,
                transaction_type="earned",
                created_at=datetime(2026, 11, 2, 12, 0),
            ),
            RewardHistoryItem(
                transaction_id=2,
                points_change=-50,
                transaction_type="redeemed",
                created_at=datetime(2026, 11, 2, 13, 0),
            ),
        ],
    )

    assert response.status is True
    assert response.reward_points == 250
    assert len(response.history) == 2
    assert response.history[0].points_change == 150
    assert response.history[1].points_change == -50


def test_reward_history_response_with_empty_history():
    response = RewardHistoryResponse(
        reward_points=0,
        history=[],
    )

    assert response.reward_points == 0
    assert response.history == []


def test_reward_history_requires_transaction_id():
    with pytest.raises(ValidationError):
        RewardHistoryItem(
            points_change=100,
            transaction_type="earned",
            created_at=datetime(2026, 11, 2, 12, 0),
        )
