
"""Tests for the authenticated reward balance endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.user import User
from app.routers.user_router import router
from app.utilities.auth import get_current_user_id


@pytest.fixture
def reward_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all([
            User(
                user_id=1,
                email="first@example.test",
                password_hash="test-hash",
                reward_points=250,
            ),
            User(
                user_id=2,
                email="second@example.test",
                password_hash="test-hash",
                reward_points=900,
            ),
        ])
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def get_test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user_id] = lambda: 1

    with TestClient(app) as client:
        yield client, app

    engine.dispose()


def test_reward_balance_returns_authenticated_users_points(reward_client):
    client, _ = reward_client

    response = client.get("/users/get-reward-points")

    assert response.status_code == 200
    assert response.json()["reward_points"] == 250


def test_reward_balance_does_not_return_other_users_points(reward_client):
    client, _ = reward_client

    response = client.get("/users/get-reward-points")

    assert response.status_code == 200
    assert response.json()["reward_points"] != 900


def test_reward_balance_missing_user_returns_404(reward_client):
    client, app = reward_client
    app.dependency_overrides[get_current_user_id] = lambda: 999

    response = client.get("/users/get-reward-points")

    assert response.status_code == 404


def test_reward_history_returns_empty_history(reward_client):
    client, _ = reward_client

    response = client.get("/users/rewards/history")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] is True
    assert isinstance(data["reward_points"], int)
    assert isinstance(data["history"], list)
    assert data["history"] == []



def test_reward_history_missing_user_returns_404(reward_client):
    client, app = reward_client
    app.dependency_overrides[get_current_user_id] = lambda: 999

    response = client.get("/users/rewards/history")

    assert response.status_code == 404

def test_reward_history_includes_earned_and_redeemed_points(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.services import user_service

    user = SimpleNamespace(
        user_id=7,
        reward_points=150,
    )

    payment = SimpleNamespace(
        payment_id=10,
        amount=226.80,
        created_at=datetime(2026, 11, 10, 12, 0),
    )

    redemption = SimpleNamespace(
        redeem_id=20,
        reward_points_redeemed=50,
        created_at="2026-11-11 12:00:00",
    )

    db = Mock()
    db.query.return_value.join.return_value.filter.return_value.all.return_value = [
        payment
    ]

    monkeypatch.setattr(
        user_service.user_dao,
        "get_user_by_id",
        Mock(return_value=user),
    )

    monkeypatch.setattr(
        user_service.user_dao,
        "get_redeem_history",
        Mock(return_value=[redemption]),
    )

    result = user_service.get_my_reward_history(
        db=db,
        user_id=7,
    )

    assert result["status"] is True
    assert result["reward_points"] == 150

    history = result["history"]

    assert len(history) == 2

    # Latest transaction first.
    assert history[0]["transaction_id"] == -20
    assert history[0]["points_change"] == -50
    assert history[0]["transaction_type"] == "redeemed"

    assert history[1]["transaction_id"] == 10
    assert history[1]["points_change"] == 226
    assert history[1]["transaction_type"] == "earned"

def test_reward_history_only_queries_authenticated_users_payments(
        reward_client, monkeypatch
):
    from app.models.payment import Payment
    from app.models.reservation import Reservation
    from app.services import user_service

    client, _ = reward_client

    original = user_service.get_my_reward_history

    def check_user(db, user_id):
        assert user_id == 1

        result = original(db, user_id)

        assert result["status"] is True
        assert isinstance(result["history"], list)

        return result

    monkeypatch.setattr(
        user_service,
        "get_my_reward_history",
        check_user,
    )

    response = client.get("/users/rewards/history")

    assert response.status_code == 200

def test_reward_history_with_real_database_records():
    from datetime import date, datetime

    from app.models.hotel import Hotel
    from app.models.payment import Payment
    from app.models.redeem_history import RedeemHistory
    from app.models.reservation import Reservation
    from app.models.room_type import RoomType

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    try:
        with Session(engine) as db:
            db.add_all([
                User(
                    user_id=1,
                    email="owner@example.test",
                    password_hash="hash",
                    reward_points=176,
                ),
                User(
                    user_id=2,
                    email="other@example.test",
                    password_hash="hash",
                    reward_points=900,
                ),
            ])

            hotel = Hotel(
                name="Test Hotel",
                hotel_token="reward-test-hotel",
            )
            db.add(hotel)
            db.flush()

            room = RoomType(
                hotel_id=hotel.hotel_id,
                type_name="Queen",
                price_per_night=100,
            )
            db.add(room)
            db.flush()

            for user_id, amount in [(1, 226.80), (2, 500.00)]:
                reservation = Reservation(
                    user_id=user_id,
                    room_type_id=room.room_type_id,
                    check_in_date=date(2026, 11, 10),
                    check_out_date=date(2026, 11, 12),
                    total_price=200,
                    status="confirmed",
                )
                db.add(reservation)
                db.flush()

                db.add(Payment(
                    reservation_id=reservation.reservation_id,
                    amount=amount,
                    payment_type="booking",
                    payment_status="paid",
                    created_at=datetime(2026, 11, 10, 12),
                ))

            db.add_all([
                RedeemHistory(
                    user_id=1,
                    reward_points_redeemed=50,
                    created_at=datetime(2026, 11, 11, 12, 0),
                ),
                RedeemHistory(
                    user_id=2,
                    reward_points_redeemed=100,
                    created_at=datetime(2026, 11, 11, 13, 0),
                ),
            ])
            db.commit()

        app = FastAPI()
        app.include_router(router)

        def test_db():
            with Session(engine) as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        app.dependency_overrides[get_current_user_id] = lambda: 1

        with TestClient(app) as client:
            response = client.get("/users/rewards/history")

        assert response.status_code == 200
        data = response.json()

        assert data["reward_points"] == 176
        assert len(data["history"]) == 2
        assert [
                   item["points_change"] for item in data["history"]
               ] == [-50, 226]
        assert [
                   item["transaction_type"] for item in data["history"]
               ] == ["redeemed", "earned"]

    finally:
        engine.dispose()
