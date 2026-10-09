"""Isolated booking cancellation tests; no MySQL connection is used."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
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


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def booking(engine):
    with Session(engine) as db:
        db.add(User(user_id=7, email="owner@example.test", password_hash="test", status="active"))
        hotel = Hotel(name="Hotel", hotel_token="test-hotel-property", street="123 Main St", city="San Jose", state="CA",
                      zip_code="95112", country="USA")
        db.add(hotel)
        db.flush()
        room = RoomType(hotel_id=hotel.hotel_id, type_name="Queen", price_per_night=100)
        db.add(room)
        db.flush()
        reservation = Reservation(
            user_id=7, room_type_id=room.room_type_id,
            check_in_date=datetime(2026, 11, 1), check_out_date=datetime(2026, 11, 3),
            total_price=100, status="confirmed",
        )
        db.add(reservation)
        db.flush()
        db.add(Payment(
            reservation_id=reservation.reservation_id, amount=108,
            payment_type="booking", payment_status="paid",
        ))
        db.commit()
        return reservation.reservation_id, hotel.hotel_id


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        ({}, "123 Main St, San Jose, CA. 95112 USA"),
        ({"city": None, "state": None, "zip_code": None}, "123 Main St. USA"),
        ({"street": None, "city": None, "state": None,
          "zip_code": None, "country": None}, ""),
    ],
)
def test_booking_list_and_detail_addresses(engine, booking, parts, expected):
    reservation_id, hotel_id = booking
    with Session(engine) as db:
        hotel = db.get(Hotel, hotel_id)
        for field, value in parts.items():
            setattr(hotel, field, value)
        db.commit()
        from app.repositories import booking_dao

        listed = booking_dao.get_all_booking_by_user_id(db, 7)
        detail = booking_dao.get_booking_by_id(db, reservation_id, 7)
        assert listed[0]["hotel_address"] == expected
        assert detail["hotel_address"] == expected


def test_cancellation_updates_all_records_and_returns_committed_state(engine, booking):
    reservation_id, _ = booking
    with Session(engine) as db:
        response = booking_service.cancel_booking(db, reservation_id, 7)

    with Session(engine) as db:
        reservation = db.get(Reservation, reservation_id)
        payments = db.scalars(select(Payment).where(Payment.reservation_id == reservation_id)).all()
        charge = next(p for p in payments if p.payment_type == "booking")
        cancellation = next(p for p in payments if p.payment_type == "cancellation")
        assert reservation.status == response.status == "cancelled"
        assert charge.payment_status == response.booking_payment_status == "refunded"
        assert cancellation.payment_status == response.cancellation_payment_status == "pending"
        assert cancellation.amount == response.cancellation_amount == 20
        assert response.reservation_id == reservation_id
        assert response.booking_payment_id == charge.payment_id
        assert response.cancellation_payment_id == cancellation.payment_id
        assert len(payments) == 2


@pytest.mark.parametrize(("reservation_id", "user_id"), [(999, 7), (1, 8)])
def test_missing_or_nonowned_reservation_is_inaccessible(engine, booking, reservation_id, user_id):
    with Session(engine) as db:
        with pytest.raises(Exception) as caught:
            booking_service.cancel_booking(db, reservation_id, user_id)
        assert caught.value.status_code == 404
    with Session(engine) as db:
        assert db.get(Reservation, booking[0]).status == "confirmed"
        assert db.scalar(select(Payment).where(Payment.payment_type == "cancellation")) is None


def test_repeat_cancellation_does_not_add_payment(engine, booking):
    with Session(engine) as db:
        booking_service.cancel_booking(db, booking[0], 7)
        with pytest.raises(Exception) as caught:
            booking_service.cancel_booking(db, booking[0], 7)
        assert caught.value.status_code == 409
    with Session(engine) as db:
        assert len(db.scalars(select(Payment)).all()) == 2


def test_ambiguous_booking_charges_do_not_change_reservation(engine, booking):
    with Session(engine) as db:
        db.add(Payment(reservation_id=booking[0], amount=108,
                       payment_type="booking", payment_status="paid"))
        db.commit()
        with pytest.raises(Exception) as caught:
            booking_service.cancel_booking(db, booking[0], 7)
        assert caught.value.status_code == 409
    with Session(engine) as db:
        assert db.get(Reservation, booking[0]).status == "confirmed"
        assert len(db.scalars(select(Payment)).all()) == 2


def test_existing_cancellation_payment_prevents_duplicate(engine, booking):
    with Session(engine) as db:
        db.add(Payment(reservation_id=booking[0], amount=20,
                       payment_type="cancellation", payment_status="pending"))
        db.commit()
        with pytest.raises(Exception) as caught:
            booking_service.cancel_booking(db, booking[0], 7)
        assert caught.value.status_code == 409
    with Session(engine) as db:
        assert db.get(Reservation, booking[0]).status == "confirmed"
        assert len(db.scalars(select(Payment)).all()) == 2


def test_failed_final_commit_rolls_back_every_change(engine, booking, monkeypatch):
    with Session(engine) as db:
        def fail_commit():
            db.flush()
            raise SQLAlchemyError("simulated persistence failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(Exception) as caught:
            booking_service.cancel_booking(db, booking[0], 7)
        assert caught.value.status_code == 500
        assert caught.value.detail == "Failed to cancel reservation"

    with Session(engine) as db:
        assert db.get(Reservation, booking[0]).status == "confirmed"
        payments = db.scalars(select(Payment)).all()
        assert len(payments) == 1
        assert payments[0].payment_status == "paid"


def test_cancellation_route_requires_authentication(engine, booking):
    app = FastAPI()
    app.include_router(booking_router)
    app.dependency_overrides[get_db] = lambda: Session(engine)

    response = TestClient(app).post(f"/bookings/cancel-booking/{booking[0]}")

    assert response.status_code == 401
