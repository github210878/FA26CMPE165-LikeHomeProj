
"""Integration tests for hotel search and revalidation."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base
from app.models.user import User
from app.models.reservation import Reservation
from app.models.payment import Payment
from app.schemas.booking_schema import BookingRequest
from app.services import booking_service

from datetime import date

import pytest
from fastapi import HTTPException

from app.schemas.hotel_schema import (
    HotelSearchRequest,
    HotelRevalidationRequest,
)
from app.services import hotel_service


def test_search_to_revalidation(monkeypatch):
    """A selected search result can be revalidated before booking."""

    calls = []

    def fake_serpapi(params):
        calls.append(params)

        if "property_token" not in params:
            return {
                "properties": [
                    {
                        "name": "Hotel A",
                        "property_token": "property-A",
                        "rate_per_night": {
                            "extracted_lowest": 100
                        },
                        "overall_rating": 4.5,
                    }
                ]
            }

        return {
            "name": "Hotel A",
            "property_token": "property-A",
            "prices": [
                {
                    "source": "Provider A",
                    "num_guests": 2,
                    "rate_per_night": {
                        "extracted_before_taxes_fees": 100
                    },
                    "total_rate": {
                        "extracted_before_taxes_fees": 200,
                        "extracted_lowest": 230,
                    },
                }
            ],
        }

    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        fake_serpapi,
    )

    monkeypatch.setattr(
        hotel_service,
        "_cache_hotels",
        lambda **kwargs: None,
    )

    search = hotel_service.search_hotels(
    HotelSearchRequest(
        q="San Jose hotels",
        check_in_date="2026-11-01",
        check_out_date="2026-11-03",
        adults=2,
        ),
        db=object(),
    )

    assert search.result_count == 1

    selected = search.properties[0]
    assert selected.property_token == "property-A"

    quote = hotel_service.revalidate_hotel(
        HotelRevalidationRequest(
            q="San Jose hotels",
            property_token=selected.property_token,
            check_in_date=date(2026, 11, 1),
            check_out_date=date(2026, 11, 3),
            adults=2,
            displayed_price_per_night=selected.price_per_night,
        )
    )

    assert quote.availability == "available"
    assert quote.property_token == selected.property_token
    assert quote.number_of_nights == 2
    assert quote.current_price_per_night == 100
    assert quote.likehome_reservation_total == 210
    assert quote.likehome_payment_amount == 226.80

    # Search and revalidation must make separate provider requests.
    assert len(calls) == 2
    assert calls[1]["property_token"] == selected.property_token


def test_unavailable_hotel_cannot_be_revalidated(monkeypatch):
    """Unavailable properties must not receive an accepted quote."""

    def fake_serpapi(params):
        return {
            "name": "Hotel A",
            "property_token": "property-A",
            "prices": [],
        }

    monkeypatch.setattr(
        hotel_service.serpapi_client,
        "search_google_hotels",
        fake_serpapi,
    )

    with pytest.raises(HTTPException) as error:
        hotel_service.revalidate_hotel(
            HotelRevalidationRequest(
                q="San Jose hotels",
                property_token="property-A",
                check_in_date=date(2026, 11, 1),
                check_out_date=date(2026, 11, 3),
                adults=2,
            )
        )

    assert error.value.status_code == 409

def test_revalidated_hotel_creates_reservation(monkeypatch):
    """A customer can book a hotel after accepting its current price."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            db.add(
                User(
                    user_id=7,
                    email="test7@example.com",
                    password_hash="test",
                )
            )
            db.commit()

        calls = []

        def fake_serpapi(params):
            calls.append(params)

            if "property_token" not in params:
                return {
                    "properties": [
                        {
                            "name": "Hotel A",
                            "property_token": "property-A",
                            "rate_per_night": {
                                "extracted_lowest": 100,
                            },
                        }
                    ]
                }

            return {
                "name": "Hotel A",
                "property_token": "property-A",
                "prices": [
                    {
                        "source": "Provider A",
                        "num_guests": 2,
                        "rate_per_night": {
                            "extracted_before_taxes_fees": 100,
                        },
                        "total_rate": {
                            "extracted_before_taxes_fees": 200,
                            "extracted_lowest": 230,
                        },
                    }
                ],
            }

        monkeypatch.setattr(
            hotel_service.serpapi_client,
            "search_google_hotels",
            fake_serpapi,
        )
        monkeypatch.setattr(
            hotel_service,
            "_cache_hotels",
            lambda **kwargs: None,
        )

        # Step 1: Search for hotels.
        search = hotel_service.search_hotels(
            HotelSearchRequest(
                q="San Jose hotels",
                check_in_date="2026-11-01",
                check_out_date="2026-11-03",
                adults=2,
            ),
            db=object(),
        )

        selected = search.properties[0]

        # Step 2: Refresh the selected hotel's quote.
        quote = hotel_service.revalidate_hotel(
            HotelRevalidationRequest(
                q="San Jose hotels",
                property_token=selected.property_token,
                check_in_date=date(2026, 11, 1),
                check_out_date=date(2026, 11, 3),
                adults=2,
                displayed_price_per_night=selected.price_per_night,
            )
        )

        assert quote.availability == "available"

        # Step 3: Customer accepts the refreshed quote.
        booking = BookingRequest(
            hotel_name=selected.name,
            hotel_token=selected.property_token,
            guest_full_name="Example Guest",
            guest_email="guest@example.com",
            q="San Jose hotels",
            check_in_date=date(2026, 11, 1),
            check_out_date=date(2026, 11, 3),
            adults=2,
            price_per_night=quote.current_price_per_night,
            accepted_payment_amount=quote.likehome_payment_amount,
        )

        # Step 4: Create the booking.
        # The booking service performs another provider recheck.
        with Session(engine) as db:
            result = booking_service.create_booking(
                db, booking, user_id=7
            )

        # Step 5: Verify the database records.
        with Session(engine) as db:
            reservation = db.get(
                Reservation, result.reservation_id
            )
            payment = db.get(Payment, result.payment_id)

            assert reservation is not None
            assert payment is not None
            assert reservation.user_id == 7
            assert reservation.total_price == pytest.approx(
                quote.likehome_reservation_total
            )
            assert payment.amount == pytest.approx(
                quote.likehome_payment_amount
            )
            assert payment.payment_status == "pending"

        # Search, explicit revalidation, booking-time recheck.
        assert len(calls) == 3

    finally:
        engine.dispose()
def test_price_change_blocks_reservation(monkeypatch):
    """Booking is rejected if the provider changes the accepted price."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            db.add(
                User(
                    user_id=7,
                    email="test7@example.com",
                    password_hash="test",
                )
            )
            db.commit()

        provider_price = {"nightly": 100}

        def fake_serpapi(params):
            if "property_token" not in params:
                return {
                    "properties": [
                        {
                            "name": "Hotel A",
                            "property_token": "property-A",
                            "rate_per_night": {
                                "extracted_lowest": 100,
                            },
                        }
                    ]
                }

            nightly = provider_price["nightly"]

            return {
                "name": "Hotel A",
                "property_token": "property-A",
                "prices": [
                    {
                        "source": "Provider A",
                        "num_guests": 2,
                        "rate_per_night": {
                            "extracted_before_taxes_fees": nightly,
                        },
                        "total_rate": {
                            "extracted_before_taxes_fees": nightly * 2,
                            "extracted_lowest": nightly * 2 + 30,
                        },
                    }
                ],
            }

        monkeypatch.setattr(
            hotel_service.serpapi_client,
            "search_google_hotels",
            fake_serpapi,
        )

        monkeypatch.setattr(
            hotel_service,
            "_cache_hotels",
            lambda **kwargs: None,
        )

        # Customer searches for a hotel.
        search = hotel_service.search_hotels(
            HotelSearchRequest(
                q="San Jose hotels",
                check_in_date="2026-11-01",
                check_out_date="2026-11-03",
                adults=2,
            ),
            db=object(),
        )

        selected = search.properties[0]

        # Customer receives a $100/night quote.
        quote = hotel_service.revalidate_hotel(
            HotelRevalidationRequest(
                q="San Jose hotels",
                property_token=selected.property_token,
                check_in_date=date(2026, 11, 1),
                check_out_date=date(2026, 11, 3),
                adults=2,
            )
        )

        booking = BookingRequest(
            hotel_name=selected.name,
            hotel_token=selected.property_token,
            guest_full_name="Example Guest",
            guest_email="guest@example.com",
            q="San Jose hotels",
            check_in_date=date(2026, 11, 1),
            check_out_date=date(2026, 11, 3),
            adults=2,
            price_per_night=quote.current_price_per_night,
            accepted_payment_amount=quote.likehome_payment_amount,
        )

        # Price increases before the customer submits the booking.
        provider_price["nightly"] = 150

        with Session(engine) as db:
            with pytest.raises(HTTPException) as error:
                booking_service.create_booking(
                    db, booking, user_id=7
                )

            assert error.value.status_code == 409

        # A rejected booking must not create reservation/payment records.
        with Session(engine) as db:
            assert db.scalars(select(Reservation)).all() == []
            assert db.scalars(select(Payment)).all() == []

    finally:
        engine.dispose()

