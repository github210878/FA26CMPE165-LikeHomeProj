
"""Tests for the disabled reservation-change confirmation endpoint."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.database import get_db
from app.routers.booking_router import router
from app.utilities.auth import get_current_user_id


VALID_REQUEST = {
    "check_in_date": "2027-11-10",
    "check_out_date": "2027-11-12",
    "quote_id": "synthetic-test-quote",
    "accept_quote": True,
    "price_per_night": 120.0,
    "accepted_payment_amount": 259.20,
}


class NoWriteDatabase:
    """Fail immediately if the disabled endpoint attempts a write."""

    def add(self, *args, **kwargs):
        raise AssertionError("Database add was attempted")

    def commit(self):
        raise AssertionError("Database commit was attempted")

    def flush(self):
        raise AssertionError("Database flush was attempted")

    def execute(self, *args, **kwargs):
        raise AssertionError("Database SQL execution was attempted")


def make_client(authenticated=True):
    app = FastAPI()
    app.include_router(router)

    database = NoWriteDatabase()
    app.dependency_overrides[get_db] = lambda: database

    if authenticated:
        app.dependency_overrides[get_current_user_id] = lambda: 7

    return TestClient(app)


def test_confirmation_requires_authentication():
    with make_client(authenticated=False) as client:
        response = client.post(
            "/bookings/1/change-confirm",
            json=VALID_REQUEST,
        )

    assert response.status_code == 401


def test_confirmation_rejects_invalid_request():
    invalid_request = {
        **VALID_REQUEST,
        "accept_quote": False,
    }

    with make_client() as client:
        response = client.post(
            "/bookings/1/change-confirm",
            json=invalid_request,
        )

    assert response.status_code == 422


def test_confirmation_is_not_available_yet():
    with make_client() as client:
        response = client.post(
            "/bookings/1/change-confirm",
            json=VALID_REQUEST,
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Reservation changes are not available yet."
    )
