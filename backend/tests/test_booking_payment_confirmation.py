"""End-to-end Sprint 4 coverage for booking, payment, and confirmation."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.user import User
from app.routers.booking_router import router as booking_router
from app.schemas.hotel_schema import HotelRevalidationResponse
from app.services import booking_service
from app.utilities import auth


@pytest.fixture
def sprint4_app(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            User(
                user_id=7,
                email="traveler@example.test",
                password_hash="test-hash",
                status="active",
            )
        )
        db.commit()

    def revalidate_hotel(info):
        assert info.property_token == "serp-property-1"
        assert info.check_in_date == date(2026, 11, 10)
        assert info.check_out_date == date(2026, 11, 12)
        return HotelRevalidationResponse(
            property_token=info.property_token,
            hotel_name="Integration Hotel",
            check_in_date=info.check_in_date,
            check_out_date=info.check_out_date,
            adults=info.adults,
            children=info.children,
            currency="USD",
            number_of_nights=2,
            availability="available",
            rate_rule="lowest_eligible_provider_base_total",
            source="Provider A",
            guest_capacity=2,
            current_price_per_night=150,
            provider_base_total=300,
            provider_total_with_taxes_fees=330,
            likehome_reservation_total=300,
            likehome_payment_amount=324,
            price_changed=None,
        )

    monkeypatch.setattr(booking_service.hotel_service, "revalidate_hotel", revalidate_hotel)
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "sprint4-e2e-test-secret-with-at-least-32-bytes")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")

    app = FastAPI()
    app.include_router(booking_router)

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    yield TestClient(app), engine
    engine.dispose()


def test_booking_payment_and_confirmation_complete_as_one_user_flow(sprint4_app):
    client, engine = sprint4_app
    token = auth.create_access_token(7, subject_type="user")
    headers = {"Authorization": f"Bearer {token}"}
    booking_body = {
        "hotel_token": "serp-property-1",
        "guest_full_name": "  Abdullah Ahmed  ",
        "guest_email": "  abdullah@example.com  ",
        "q": "San Jose hotels",
        "adults": 2,
        "children": 0,
        "currency": "USD",
        "gl": "us",
        "hl": "en",
        "check_in_date": "2026-11-10",
        "check_out_date": "2026-11-12",
        "price_per_night": 150,
        "accepted_payment_amount": 324,
    }

    created = client.post("/bookings/create", json=booking_body, headers=headers)

    assert created.status_code == 200, created.text
    booking = created.json()
    assert booking["user_id"] == 7
    assert booking["booking_reference"] == f"LH-{booking['reservation_id']:08d}"
    assert booking["status"] == "confirmed"

    payment_before = client.get(
        f"/bookings/get-payment-details/{booking['payment_id']}", headers=headers
    )
    assert payment_before.status_code == 200
    assert payment_before.json() == {
        "payment_id": booking["payment_id"],
        "reservation_id": booking["reservation_id"],
        "amount": 324.0,
        "payment_type": "booking",
        "payment_status": "pending",
    }

    detail_before = client.get(
        f"/bookings/get-booking-details/{booking['reservation_id']}",
        headers=headers,
    )
    assert detail_before.status_code == 200
    assert detail_before.json() == {
        "reservation_id": booking["reservation_id"],
        "hotel_name": "Integration Hotel",
        "room_type_name": "Lowest available rate",
        "hotel_address": "",
        "hotel_phone": None,
        "hotel_description": None,
        "room_description": "Provider: Provider A",
        "check_in_date": "2026-11-10",
        "check_out_date": "2026-11-12",
        "price_per_night": 150.0,
        "total_price": 300.0,
        "status": "confirmed",
        "guest_full_name": "Abdullah Ahmed",
        "guest_email": "abdullah@example.com",
    }

    paid = client.post(f"/bookings/pay/{booking['payment_id']}", headers=headers)
    paid_again = client.post(f"/bookings/pay/{booking['payment_id']}", headers=headers)

    assert paid.status_code == paid_again.status_code == 200
    assert paid.json() == paid_again.json() == {
        **payment_before.json(),
        "payment_status": "paid",
    }

    payments = client.get("/bookings/get-all-payments", headers=headers)
    bookings = client.get("/bookings/get-all-bookings", headers=headers)
    confirmation = client.get(
        f"/bookings/get-booking-details/{booking['reservation_id']}",
        headers=headers,
    )

    assert payments.status_code == bookings.status_code == confirmation.status_code == 200
    assert payments.json() == [paid.json()]
    assert bookings.json() == [
        {
            "reservation_id": booking["reservation_id"],
            "hotel_name": "Integration Hotel",
            "room_type_name": "Lowest available rate",
            "hotel_address": "",
            "hotel_phone": None,
            "hotel_description": None,
            "room_description": "Provider: Provider A",
            "check_in_date": "2026-11-10",
            "check_out_date": "2026-11-12",
            "price_per_night": 150.0,
            "total_price": 300.0,
            "status": "confirmed",
        }
    ]
    assert confirmation.json()["status"] == "confirmed"
    assert confirmation.json()["reservation_id"] == booking["reservation_id"]

    with Session(engine) as db:
        reservations = db.scalars(select(Reservation)).all()
        payments_in_db = db.scalars(select(Payment)).all()
        assert len(reservations) == 1
        assert len(payments_in_db) == 1
        assert reservations[0].status == "confirmed"
        assert payments_in_db[0].payment_status == "paid"
        assert db.get(User, 7).reward_points == 324
