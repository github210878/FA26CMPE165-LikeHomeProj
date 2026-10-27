
"""Tests for the authenticated account-bookings endpoint."""

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config.database import Base, get_db
from app.models.hotel import Hotel
from app.models.room_type import RoomType
from app.models.reservation import Reservation
from app.repositories import booking_dao
from app.routers.booking_router import router
from app.services import booking_service
from app.utilities.auth import get_current_user_id


# TEST 1: Returns booking information
def test_account_bookings_returns_expected_fields(monkeypatch):
    booking = {
        "reservation_id": 12,
        "hotel_name": "Example Hotel",
        "room_type_name": "Queen room",
        "hotel_address": "123 Main St",
        "hotel_phone": None,
        "hotel_description": None,
        "room_description": "One queen bed",
        "check_in_date": date(2026, 11, 5),
        "check_out_date": date(2026, 11, 8),
        "price_per_night": 125.0,
        "total_price": 375.0,
        "status": "confirmed",
    }

    captured = {}

    def fake_get_bookings(db, user_id):
        captured["user_id"] = user_id
        return [booking]

    monkeypatch.setattr(
        booking_service,
        "get_all_booking_by_user_id",
        fake_get_bookings,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user_id] = lambda: 7

    client = TestClient(app)
    response = client.get("/bookings/get-all-bookings")

    assert response.status_code == 200
    assert captured["user_id"] == 7

    result = response.json()
    assert len(result) == 1
    assert result[0]["reservation_id"] == 12
    assert result[0]["hotel_name"] == "Example Hotel"
    assert result[0]["check_in_date"] == "2026-11-05"
    assert result[0]["status"] == "confirmed"


# TEST 2: Returns empty list if no bookings
def test_account_bookings_empty_list(monkeypatch):
    monkeypatch.setattr(
        booking_service,
        "get_all_booking_by_user_id",
        lambda db, user_id: [],
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user_id] = lambda: 7

    client = TestClient(app)
    response = client.get("/bookings/get-all-bookings")

    assert response.status_code == 200
    assert response.json() == []


# TEST 3: Returns revised reservation details
def test_account_bookings_reflects_changed_reservation(monkeypatch):
    updated_booking = {
        "reservation_id": 12,
        "hotel_name": "Example Hotel",
        "room_type_name": "Queen room",
        "hotel_address": "123 Main St",
        "hotel_phone": None,
        "hotel_description": None,
        "room_description": "One queen bed",
        "check_in_date": date(2026, 11, 10),
        "check_out_date": date(2026, 11, 13),
        "price_per_night": 150.0,
        "total_price": 450.0,
        "status": "confirmed",
    }

    def fake_get_bookings(db, user_id):
        assert user_id == 7
        return [updated_booking]

    monkeypatch.setattr(
        booking_service,
        "get_all_booking_by_user_id",
        fake_get_bookings,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user_id] = lambda: 7

    client = TestClient(app)
    response = client.get("/bookings/get-all-bookings")

    assert response.status_code == 200

    result = response.json()
    assert len(result) == 1
    assert result[0]["reservation_id"] == 12
    assert result[0]["check_in_date"] == "2026-11-10"
    assert result[0]["check_out_date"] == "2026-11-13"
    assert result[0]["total_price"] == 450.0
    assert result[0]["status"] == "confirmed"


# TEST 4: Reads updated reservations from a temporary SQLite database
def test_account_bookings_updates_from_database():
    """Verify changes to stored reservations appear in booking results."""

    engine = create_engine("sqlite:///:memory:")

    try:
        Base.metadata.create_all(
            engine,
            tables=[
                Hotel.__table__,
                RoomType.__table__,
                Reservation.__table__,
            ],
        )

        with Session(engine) as db:
            hotel = Hotel(
                hotel_id=1,
                hotel_token="test-hotel",
                name="Example Hotel",
                city="San Jose",
                state="CA",
            )

            room = RoomType(
                room_type_id=1,
                hotel_id=1,
                type_name="Queen Room",
                price_per_night=125.0,
            )

            original = Reservation(
                reservation_id=12,
                user_id=7,
                room_type_id=1,
                check_in_date=date(2026, 11, 5),
                check_out_date=date(2026, 11, 8),
                total_price=375.0,
                status="confirmed",
            )

            other_booking = Reservation(
                reservation_id=13,
                user_id=8,
                room_type_id=1,
                check_in_date=date(2026, 11, 15),
                check_out_date=date(2026, 11, 18),
                total_price=375.0,
                status="confirmed",
            )

            db.add_all([hotel, room, original, other_booking])
            db.commit()

            # Check original booking data.
            before = booking_dao.get_all_booking_by_user_id(db, 7)

            assert len(before) == 1
            assert before[0]["reservation_id"] == 12
            assert before[0]["check_in_date"] == date(2026, 11, 5)
            assert before[0]["total_price"] == 375.0

            # Simulate changes to the saved reservation.
            original.check_in_date = date(2026, 11, 10)
            original.check_out_date = date(2026, 11, 13)
            original.total_price = 450.0
            db.commit()

            # Verify the owner sees the updated booking.
            after = booking_dao.get_all_booking_by_user_id(db, 7)

            assert len(after) == 1
            assert after[0]["reservation_id"] == 12
            assert after[0]["check_in_date"] == date(2026, 11, 10)
            assert after[0]["check_out_date"] == date(2026, 11, 13)
            assert after[0]["total_price"] == 450.0
            assert after[0]["status"] == "confirmed"

            # Verify the other user's booking is still separate.
            other_user_results = booking_dao.get_all_booking_by_user_id(db, 8)

            assert len(other_user_results) == 1
            assert other_user_results[0]["reservation_id"] == 13

    finally:
        engine.dispose()
