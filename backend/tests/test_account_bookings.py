"""Tests for the authenticated account-bookings endpoint."""

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.database import get_db
from app.routers.booking_router import router
from app.services import booking_service
from app.utilities.auth import get_current_user_id


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
