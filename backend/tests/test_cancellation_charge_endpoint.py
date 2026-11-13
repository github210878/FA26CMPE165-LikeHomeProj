"""Tests for the read-only cancellation-charge preview endpoint."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.routers.booking_router import router as booking_router
from app.services import booking_service
from app.utilities.auth import get_current_user_id


@pytest.fixture
def charge_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(user_id=7, email="owner@example.test", password_hash="hash"))
        db.add(User(user_id=8, email="other@example.test", password_hash="hash"))
        hotel = Hotel(name="Hotel", hotel_token="property-1")
        db.add(hotel)
        db.flush()
        room = RoomType(
            hotel_id=hotel.hotel_id,
            type_name="Queen",
            price_per_night=100,
        )
        db.add(room)
        db.flush()
        db.add_all(
            [
                Reservation(
                    reservation_id=1,
                    user_id=7,
                    room_type_id=room.room_type_id,
                    check_in_date=date(2026, 11, 1),
                    check_out_date=date(2026, 11, 3),
                    total_price=99.99,
                    status="confirmed",
                ),
                Reservation(
                    reservation_id=2,
                    user_id=7,
                    room_type_id=room.room_type_id,
                    check_in_date=date(2026, 12, 1),
                    check_out_date=date(2026, 12, 3),
                    total_price=100,
                    status="cancelled",
                ),
            ]
        )
        db.add(
            Payment(
                reservation_id=1,
                amount=107.99,
                payment_type="booking",
                payment_status="pending",
            )
        )
        db.commit()

    app = FastAPI()
    app.include_router(booking_router)

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    yield app, engine
    engine.dispose()


def test_charge_preview_returns_policy_result_without_side_effects(charge_app):
    app, engine = charge_app
    app.dependency_overrides[get_current_user_id] = lambda: 7

    response = TestClient(app).get("/bookings/1/cancellation-charge")

    assert response.status_code == 200
    assert response.json() == {
        "reservation_id": 1,
        "reservation_total": 99.99,
        "cancellation_fee_rate": 0.2,
        "cancellation_charge": 20.0,
        "currency": "USD",
        "reservation_status": "confirmed",
    }
    with Session(engine) as db:
        assert db.get(Reservation, 1).status == "confirmed"
        assert len(db.scalars(select(Payment)).all()) == 1
        assert db.get(User, 7).reward_points == 0


@pytest.mark.parametrize(
    ("reservation_id", "user_id", "status"),
    [(999, 7, 404), (1, 8, 404), (2, 7, 409)],
)
def test_charge_preview_rejects_missing_nonowned_and_nonconfirmable(
    charge_app, reservation_id, user_id, status
):
    app, _ = charge_app
    app.dependency_overrides[get_current_user_id] = lambda: user_id

    response = TestClient(app).get(
        f"/bookings/{reservation_id}/cancellation-charge"
    )

    assert response.status_code == status


def test_charge_preview_requires_authentication(charge_app):
    app, _ = charge_app

    response = TestClient(app).get("/bookings/1/cancellation-charge")

    assert response.status_code == 401


def test_cancellation_recalculates_charge_after_preview(charge_app):
    app, engine = charge_app
    app.dependency_overrides[get_current_user_id] = lambda: 7
    client = TestClient(app)

    preview = client.get("/bookings/1/cancellation-charge")
    assert preview.status_code == 200

    with Session(engine) as db:
        db.get(Reservation, 1).total_price = 200
        db.commit()

    with Session(engine) as db:
        cancelled = booking_service.cancel_booking(db, 1, 7)
    assert cancelled.cancellation_amount == 40
