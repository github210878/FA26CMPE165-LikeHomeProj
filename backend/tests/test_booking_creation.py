"""Booking creation tests use only in-memory SQLite and test-local JWTs."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.routers.booking_router import router as booking_router
from app.schemas.booking_schema import BookingRequest, BookingResponse
from app.services import booking_service
from app.utilities import auth


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def request(*, check_in=date(2026, 11, 1), check_out=date(2026, 11, 2), **overrides):
    fields = dict(
        hotel_name="Hotel A",
        hotel_token="property-A",
        room_type_name="Queen",
        room_type_description="One queen bed",
        check_in_date=check_in,
        check_out_date=check_out,
        price_per_night=100,
    )
    fields.update(overrides)
    return BookingRequest(**fields)


@pytest.mark.parametrize(
    ("check_out", "nights", "total", "payment_amount"),
    [
        (date(2026, 11, 2), 1, 105.00, 113.40),
        (date(2026, 11, 4), 3, 315.00, 340.20),
    ],
)
def test_stay_pricing_and_single_commit(engine, monkeypatch, check_out, nights, total, payment_amount):
    with Session(engine) as db:
        original_commit = db.commit
        commits = []

        def counted_commit():
            commits.append(True)
            original_commit()

        monkeypatch.setattr(db, "commit", counted_commit)
        response = booking_service.create_booking(
            db, request(check_out=check_out), user_id=7
        )
        assert len(commits) == 1
        assert isinstance(response, BookingResponse)
        assert response.user_id == 7

    with Session(engine) as db:
        hotel = db.get(Hotel, response.hotel_id)
        room = db.get(RoomType, response.room_type_id)
        reservation = db.get(Reservation, response.reservation_id)
        payment = db.get(Payment, response.payment_id)
        assert hotel.hotel_token == "property-A"
        assert room.type_name == "Queen"
        assert reservation.user_id == 7
        assert (reservation.check_out_date - reservation.check_in_date).days == nights
        assert reservation.total_price == pytest.approx(total)
        assert payment.amount == pytest.approx(payment_amount)
        assert payment.payment_type == "booking"
        assert payment.payment_status == "pending"


@pytest.mark.parametrize(
    ("check_in", "check_out"),
    [
        (date(2026, 11, 1), date(2026, 11, 1)),
        (date(2026, 11, 2), date(2026, 11, 1)),
    ],
)
def test_invalid_date_range_is_a_validation_error(check_in, check_out):
    with pytest.raises(ValidationError):
        request(check_in=check_in, check_out=check_out)


def test_money_is_rounded_to_cents(engine):
    with Session(engine) as db:
        response = booking_service.create_booking(
            db,
            request(price_per_night=99.99, check_out_date=date(2026, 11, 3)),
            7,
        )
    with Session(engine) as db:
        assert db.get(Reservation, response.reservation_id).total_price == pytest.approx(209.98)
        assert db.get(Payment, response.payment_id).amount == pytest.approx(226.78)


@pytest.mark.parametrize(
    "missing_field",
    ["hotel_name", "hotel_token", "room_type_name", "check_in_date", "check_out_date", "price_per_night"],
)
def test_database_required_fields_are_request_required(missing_field):
    fields = request().model_dump()
    del fields[missing_field]
    with pytest.raises(ValidationError):
        BookingRequest(**fields)


@pytest.mark.parametrize("price", [0, -1, float("inf"), float("nan")])
def test_invalid_nightly_price_is_rejected(price):
    with pytest.raises(ValidationError):
        request(price_per_night=price)


def test_rounding_to_zero_and_oversized_total_are_rejected(engine):
    with Session(engine) as db:
        with pytest.raises(HTTPException) as zero:
            booking_service.create_booking(db, request(price_per_night=0.001), 7)
        assert zero.value.status_code == 422
        with pytest.raises(HTTPException) as too_large:
            booking_service.create_booking(
                db, request(price_per_night=99999999, check_out=date(2026, 11, 4)), 7
            )
        assert too_large.value.status_code == 422
    with Session(engine) as db:
        assert db.query(Hotel).count() == 0


def test_existing_hotel_and_room_are_reused_by_token(engine):
    with Session(engine) as db:
        first = booking_service.create_booking(db, request(), user_id=7)
        second = booking_service.create_booking(
            db,
            request(hotel_name="Renamed by browser", check_in_date=date(2026, 11, 5), check_out_date=date(2026, 11, 6)),
            user_id=8,
        )
        assert first.hotel_id == second.hotel_id
        assert first.room_type_id == second.room_type_id
        assert db.query(Hotel).count() == 1
        assert db.query(RoomType).count() == 1


def test_cancelled_stay_no_longer_blocks_overlap_but_confirmed_stay_does(engine):
    with Session(engine) as db:
        first = booking_service.create_booking(db, request(), 7)
        with pytest.raises(HTTPException) as overlap:
            booking_service.create_booking(db, request(), 7)
        assert overlap.value.status_code == 400
        db.get(Reservation, first.reservation_id).status = "cancelled"
        db.commit()
        second = booking_service.create_booking(db, request(), 7)
        assert second.reservation_id != first.reservation_id


def test_payment_stage_failure_rolls_back_all_records(engine, monkeypatch):
    original_stage = booking_service.booking_dao.stage_booking_record

    def fail_on_payment(db, record):
        if isinstance(record, Payment):
            raise SQLAlchemyError("simulated payment failure")
        return original_stage(db, record)

    monkeypatch.setattr(booking_service.booking_dao, "stage_booking_record", fail_on_payment)
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            booking_service.create_booking(db, request(), 7)
        assert error.value.status_code == 500
        assert error.value.detail == "Failed to create reservation"
    with Session(engine) as db:
        for model in (Hotel, RoomType, Reservation, Payment):
            assert db.query(model).count() == 0


def test_commit_failure_rolls_back_all_records(engine, monkeypatch):
    with Session(engine) as db:
        def fail_commit():
            raise SQLAlchemyError("failed")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(HTTPException) as error:
            booking_service.create_booking(db, request(), 7)
        assert error.value.status_code == 500
    with Session(engine) as db:
        for model in (Hotel, RoomType, Reservation, Payment):
            assert db.query(model).count() == 0


def test_create_http_contract_uses_authenticated_user_and_rejects_partner(engine, monkeypatch):
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "isolated-booking-creation-secret-32")
    monkeypatch.setattr(
        auth.user_dao,
        "get_user_by_id",
        lambda **_: SimpleNamespace(status="active", session_version=0),
    )
    app = FastAPI()
    app.include_router(booking_router)

    def test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    client = TestClient(app)
    body = request().model_dump(mode="json")
    user_token = auth.create_access_token(7, subject_type="user")
    partner_token = auth.create_access_token(7, subject_type="partner")
    assert client.post("/bookings/create", json=body).status_code == 401
    assert client.post(
        "/bookings/create", json=body,
        headers={"Authorization": f"Bearer {partner_token}"},
    ).status_code == 401
    assert client.post(
        "/bookings/create", json={**body, "user_id": 99},
        headers={"Authorization": f"Bearer {user_token}"},
    ).status_code == 422
    response = client.post(
        "/bookings/create", json=body,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "user_id", "hotel_id", "room_type_id", "reservation_id", "payment_id"
    }
    assert response.json()["user_id"] == 7
    with Session(engine) as db:
        assert db.get(Reservation, response.json()["reservation_id"]).user_id == 7
