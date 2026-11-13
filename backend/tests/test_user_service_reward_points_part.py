from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.services import user_service
from fastapi import HTTPException


@pytest.fixture
def db():
    return Mock()


@pytest.fixture
def user():
    return SimpleNamespace(
        user_id=1,
        reward_points=1000,
    )


@pytest.fixture
def user_balance():
    return SimpleNamespace(
        user_id=1,
        balance=Decimal("50.00"),
    )


def test_get_my_reward_points(monkeypatch, db, user):
    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    result = user_service.get_my_reward_points(
        db=db,
        user_id=1,
    )

    assert result == {
        "status": True,
        "reward_points": 1000,
    }


def test_get_my_reward_points_user_not_found(monkeypatch, db):
    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        user_service.get_my_reward_points(
            db=db,
            user_id=1,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"


def test_get_balance(monkeypatch, db, user):
    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_balance",
        Mock(return_value=Decimal("50.00")),
    )

    result = user_service.get_balance(
        db=db,
        user_id=1,
    )

    assert result == {
        "status": True,
        "balance": Decimal("50.00"),
    }


def test_redeem_reward_points(monkeypatch, db, user, user_balance):
    user_dao = user_service.user_dao

    monkeypatch.setattr(
        user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    monkeypatch.setattr(
        user_dao,
        "get_user_balance",
        Mock(return_value=Decimal("50.00")),
    )

    updated_user = SimpleNamespace(
        user_id=1,
        reward_points=800,
    )

    updated_balance = SimpleNamespace(
        user_id=1,
        balance=Decimal("52.00"),
    )

    update_account_mock = Mock(return_value=(updated_user, updated_balance))

    create_history_mock = Mock(
        return_value=SimpleNamespace(
            user_id=1,
            reward_points_redeemed=200,
        )
    )

    monkeypatch.setattr(
        user_dao,
        "update_user_reward_points_and_balance",
        update_account_mock,
    )

    monkeypatch.setattr(
        user_dao,
        "create_redeem_history",
        create_history_mock,
    )

    result = user_service.redeem_reward_points(
        db=db,
        user_id=1,
        amount=200,
    )

    assert result["status"] is True
    assert result["new_reward_points"] == 800

    # 你的 service 当前返回的是 user_balance 对象.
    # 修正 service 后, 应该测试这个:
    assert result["new_balance"] == Decimal("52.00")

    update_account_mock.assert_called_once_with(
        db=db,
        user_id=1,
        new_reward_points=800,
        new_balance=Decimal("52.00"),
    )

    create_history_mock.assert_called_once_with(
        db=db,
        user_id=1,
        reward_points_redeemed=200,
    )


def test_redeem_reward_points_insufficient_points(
    monkeypatch,
    db,
    user,
):
    user.reward_points = 100

    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    update_mock = Mock()

    monkeypatch.setattr(
        user_service.user_dao,
        "update_user_reward_points_and_balance",
        update_mock,
    )

    with pytest.raises(HTTPException) as exc_info:
        user_service.redeem_reward_points(
            db=db,
            user_id=1,
            amount=200,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Insufficient reward points to redeem"

    update_mock.assert_not_called()


def test_redeem_reward_points_rejects_zero_amount(
    monkeypatch,
    db,
    user,
):
    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    with pytest.raises(HTTPException) as exc_info:
        user_service.redeem_reward_points(
            db=db,
            user_id=1,
            amount=0,
        )

    assert exc_info.value.status_code == 400


def test_get_redeem_history(monkeypatch, db, user):
    redeem_history = [
        SimpleNamespace(
            redeem_id=1,
            user_id=1,
            reward_points_redeemed=200,
        )
    ]

    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_redeem_history",
        Mock(return_value=redeem_history),
    )

    result = user_service.get_redeem_history(
        db=db,
        user_id=1,
    )

    assert result == {
        "status": True,
        "redeem_history": redeem_history,
    }


def test_get_reservation_history(monkeypatch, db, user):
    reservations = [
        SimpleNamespace(
            reservation_id=10,
            user_id=1,
        )
    ]

    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_reservation_history",
        Mock(return_value=reservations),
    )

    result = user_service.get_reservation_history(
        db=db,
        user_id=1,
    )

    assert result == {
        "status": True,
        "reservations": reservations,
    }


def test_get_payment_history(monkeypatch, db, user):
    payments = [
        SimpleNamespace(
            payment_id=20,
            amount=Decimal("100.00"),
        )
    ]

    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_payment_history",
        Mock(return_value=payments),
    )

    result = user_service.get_payment_history(
        db=db,
        user_id=1,
    )

    assert result == {
        "status": True,
        "payments": payments,
    }


def test_get_reward_points_history(
    monkeypatch,
    db,
    user,
):
    payment = SimpleNamespace(
        payment_id=1,
        amount=Decimal("100.00"),
        payment_status="paid",
        created_at=2,
    )

    redeem = SimpleNamespace(
        redeem_id=1,
        reward_points_redeemed=200,
        created_at=1,
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_payment_history",
        Mock(return_value=[payment]),
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_redeem_history",
        Mock(return_value=[redeem]),
    )

    result = user_service.get_reward_points_history(
        db=db,
        user_id=1,
    )

    history = result["reward_points_history"]

    assert result["status"] is True
    assert len(history) == 2

    assert history[0]["type"] == "earned"
    assert history[0]["reward_points_change"] == (
        Decimal("100.00") * user_service.REWARD_POINT_CONVERSION_RATE
    )

    assert history[1]["type"] == "redeemed"
    assert history[1]["reward_points_change"] == -200
