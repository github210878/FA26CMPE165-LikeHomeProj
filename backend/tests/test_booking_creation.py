"""Booking creation tests use only in-memory SQLite and test-local JWTs."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import mysql
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
from app.repositories import booking_dao
from app.schemas.booking_schema import BookingRequest, BookingResponse
from app.schemas.hotel_schema import HotelRevalidationResponse
from app.services import booking_service
from app.utilities import auth


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            User(user_id=user_id, email=f"user{user_id}@example.com", password_hash="test")
            for user_id in (7, 8)
        ])
        db.commit()
    yield engine
    engine.dispose()


def request(*, check_in=date(2026, 11, 1), check_out=date(2026, 11, 2), **overrides):
    fields = dict(
        hotel_name="Hotel A",
        hotel_token="property-A",
        guest_full_name="  Person Example  ",
        guest_email="  person@example.com  ",
        q="San Jose hotels",
        room_type_name="Queen",
        room_type_description="One queen bed",
        check_in_date=check_in,
        check_out_date=check_out,
        price_per_night=100,
    )
    fields.update(overrides)
    if "accepted_payment_amount" not in fields:
        base = Decimal(str(fields["price_per_night"])) * (fields["check_out_date"] - fields["check_in_date"]).days
        reservation = (base * Decimal("1.05")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fields["accepted_payment_amount"] = float((reservation * Decimal("1.08")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return BookingRequest(**fields)


@pytest.fixture(autouse=True)
def mock_revalidation(monkeypatch):
    def quote(info):
        nights = (info.check_out_date - info.check_in_date).days
        return HotelRevalidationResponse(
            property_token=info.property_token, hotel_name="Hotel A",
            check_in_date=info.check_in_date, check_out_date=info.check_out_date,
            adults=info.adults, children=info.children, currency="USD",
            number_of_nights=nights, availability="available",
            rate_rule="lowest_eligible_provider_base_total", source="Provider A",
            guest_capacity=2, current_price_per_night=100,
            provider_base_total=100 * nights,
            provider_total_with_taxes_fees=120 * nights,
            likehome_reservation_total=105 * nights,
            likehome_payment_amount=float(Decimal("113.40") * nights), price_changed=None,
        )
    monkeypatch.setattr(booking_service.hotel_service, "revalidate_hotel", quote)


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
        assert room.type_name == "Lowest available rate"
        assert reservation.user_id == 7
        assert reservation.guest_full_name == "Person Example"
        assert reservation.guest_email == "person@example.com"
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


def test_guest_contact_schema_validation():
    fields = request().model_dump()
    for missing in ("guest_full_name", "guest_email"):
        incomplete = {key: value for key, value in fields.items() if key != missing}
        with pytest.raises(ValidationError):
            BookingRequest(**incomplete)
    for invalid_name in (" ", "x" * 101):
        with pytest.raises(ValidationError):
            request(guest_full_name=invalid_name)
    for invalid_email in ("not-an-email", "a" * 95 + "@example.com"):
        with pytest.raises(ValidationError):
            request(guest_email=invalid_email)
    assert request().guest_full_name == "Person Example"
    assert request().guest_email == "person@example.com"


def test_guest_detail_is_owned_and_legacy_nulls_are_safe(engine):
    with Session(engine) as db:
        created = booking_service.create_booking(db, request(), 7)
        detail = booking_dao.get_booking_by_id(db, created.reservation_id, 7)
        assert detail["guest_full_name"] == "Person Example"
        assert detail["guest_email"] == "person@example.com"
        assert booking_dao.get_booking_by_id(db, created.reservation_id, 8) is None
        reservation = db.get(Reservation, created.reservation_id)
        reservation.guest_full_name = None
        reservation.guest_email = None
        db.commit()
        legacy = booking_dao.get_booking_by_id(db, created.reservation_id, 7)
        assert legacy["guest_full_name"] is None
        assert legacy["guest_email"] is None
        assert "guest_email" not in booking_dao.get_all_booking_by_user_id(db, 7)[0]


def test_guest_contact_does_not_change_trusted_price(engine):
    with Session(engine) as db:
        first = booking_service.create_booking(db, request(), 7)
        second = booking_service.create_booking(
            db, request(guest_full_name="Other Guest", guest_email="other@example.com"), 8
        )
        assert db.get(Reservation, first.reservation_id).total_price == db.get(Reservation, second.reservation_id).total_price
        assert db.get(Payment, first.payment_id).amount == db.get(Payment, second.payment_id).amount


def test_money_is_rounded_to_cents(engine, monkeypatch):
    original = booking_service.hotel_service.revalidate_hotel
    def quote_9999(info):
        return original(info).model_copy(update={
            "current_price_per_night": 99.99,
            "provider_base_total": 199.98,
            "likehome_reservation_total": 209.98,
            "likehome_payment_amount": 226.78,
        })
    # Fixture default quote is intentionally independent of submitted price.
    monkeypatch.setattr(booking_service.hotel_service, "revalidate_hotel", quote_9999)
    with Session(engine) as db:
        response = booking_service.create_booking(
            db, request(price_per_night=99.99, check_out_date=date(2026, 11, 3)), 7,
        )
    with Session(engine) as db:
        assert db.get(Reservation, response.reservation_id).total_price == pytest.approx(209.98)
        assert db.get(Payment, response.payment_id).amount == pytest.approx(226.78)


@pytest.mark.parametrize(
    "missing_field",
    ["hotel_token", "q", "check_in_date", "check_out_date", "price_per_night", "accepted_payment_amount"],
)
def test_database_required_fields_are_request_required(missing_field):
    fields = request().model_dump()
    del fields[missing_field]
    with pytest.raises(ValidationError):
        BookingRequest(**fields)


@pytest.mark.parametrize("price", [0, -1, float("inf"), float("nan")])
def test_invalid_nightly_price_is_rejected(price):
    with pytest.raises(ValidationError):
        request(price_per_night=price, accepted_payment_amount=113.40)


def test_unaccepted_price_is_rejected_without_writes(engine):
    with Session(engine) as db:
        with pytest.raises(HTTPException) as zero:
            booking_service.create_booking(db, request(price_per_night=0.001, accepted_payment_amount=113.40), 7)
        assert zero.value.status_code == 409
        with pytest.raises(HTTPException) as changed:
            booking_service.create_booking(db, request(price_per_night=1), 7)
        assert changed.value.status_code == 409
        with pytest.raises(HTTPException) as changed_total:
            booking_service.create_booking(db, request(accepted_payment_amount=1), 7)
        assert changed_total.value.status_code == 409
    with Session(engine) as db:
        assert db.query(Hotel).count() == 0


def test_provider_unavailable_prevents_booking_write(engine, monkeypatch):
    def unavailable(_):
        raise HTTPException(status_code=409, detail="No usable rate for this stay; search again")
    monkeypatch.setattr(booking_service.hotel_service, "revalidate_hotel", unavailable)
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            booking_service.create_booking(db, request(), 7)
        assert error.value.status_code == 409
    with Session(engine) as db:
        assert db.query(Reservation).count() == 0
        assert db.query(Payment).count() == 0


def test_existing_hotel_and_room_are_reused_by_token(engine):
    with Session(engine) as db:
        first = booking_service.create_booking(db, request(hotel_name="Browser supplied", room_type_name="Penthouse"), user_id=7)
        second = booking_service.create_booking(
            db,
            request(hotel_name="Renamed by browser", check_in_date=date(2026, 11, 5), check_out_date=date(2026, 11, 6)),
            user_id=8,
        )
        assert first.hotel_id == second.hotel_id
        assert first.room_type_id == second.room_type_id
        assert db.query(Hotel).count() == 1
        assert db.query(RoomType).count() == 1
        assert db.get(Hotel, first.hotel_id).name == "Hotel A"
        assert db.get(RoomType, first.room_type_id).type_name == "Lowest available rate"


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


@pytest.mark.parametrize(
    ("new_check_in", "new_check_out", "overlaps"),
    [
        (date(2026, 11, 10), date(2026, 11, 12), True),   # same interval
        (date(2026, 11, 11), date(2026, 11, 13), True),   # partial overlap
        (date(2026, 11, 9), date(2026, 11, 13), True),    # new contains existing
        (date(2026, 11, 11), date(2026, 11, 12), True),   # existing contains new
        (date(2026, 11, 12), date(2026, 11, 14), False),  # adjacent checkout
        (date(2026, 11, 8), date(2026, 11, 10), False),   # completely before
    ],
)
def test_half_open_overlap_boundaries(engine, new_check_in, new_check_out, overlaps):
    with Session(engine) as db:
        booking_service.create_booking(db, request(
            check_in=date(2026, 11, 10), check_out=date(2026, 11, 12)
        ), 7)
        next_request = request(check_in=new_check_in, check_out=new_check_out)
        if overlaps:
            with pytest.raises(HTTPException) as caught:
                booking_service.create_booking(db, next_request, 7)
            assert caught.value.status_code == 400
        else:
            booking_service.create_booking(db, next_request, 7)
        expected = 1 if overlaps else 2
        assert db.query(Reservation).count() == expected
        assert db.query(Payment).count() == expected


def test_completed_blocks_and_different_users_are_independent(engine):
    with Session(engine) as db:
        created = booking_service.create_booking(db, request(), 7)
        db.get(Reservation, created.reservation_id).status = "completed"
        db.commit()
        with pytest.raises(HTTPException) as caught:
            booking_service.create_booking(db, request(), 7)
        assert caught.value.status_code == 400
        other = booking_service.create_booking(db, request(), 8)
        assert db.get(Reservation, other.reservation_id).user_id == 8
        assert db.query(Reservation).count() == 2
        assert db.query(Payment).count() == 2


def test_owner_lock_uses_mysql_for_update_on_unique_user_row():
    statements = []

    class Result:
        def scalar_one_or_none(self):
            return 7

    class RecordingDb:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    assert booking_dao.lock_user_for_booking(RecordingDb(), 7)
    sql = str(statements[0].compile(dialect=mysql.dialect()))
    assert "FROM users" in sql
    assert "users.user_id =" in sql
    assert "users.status =" in sql
    assert sql.endswith("FOR UPDATE")


def test_provider_check_precedes_lock_and_overlap_check(engine, monkeypatch):
    events = []
    original_quote = booking_service.hotel_service.revalidate_hotel
    original_lock = booking_dao.lock_user_for_booking
    original_overlap = booking_dao.check_if_user_booked_by_date_range

    def quote(info):
        events.append("provider")
        return original_quote(info)

    def lock(db, user_id):
        events.append("lock")
        return original_lock(db, user_id)

    def overlap(db, user_id, check_in, check_out):
        events.append("overlap")
        return original_overlap(db, user_id, check_in, check_out)

    monkeypatch.setattr(booking_service.hotel_service, "revalidate_hotel", quote)
    monkeypatch.setattr(booking_dao, "lock_user_for_booking", lock)
    monkeypatch.setattr(booking_dao, "check_if_user_booked_by_date_range", overlap)
    with Session(engine) as db:
        # Model the plain auth read that precedes the booking service.
        db.execute(select(User.user_id).where(User.user_id == 7)).scalar_one()
        original_rollback = db.rollback

        def rollback():
            events.append("rollback")
            original_rollback()

        monkeypatch.setattr(db, "rollback", rollback)
        booking_service.create_booking(db, request(), 7)
    assert events == ["provider", "rollback", "lock", "overlap"]


def test_lock_failure_rolls_back_without_booking_records(engine, monkeypatch):
    def lock_failure(*_):
        raise SQLAlchemyError("private lock failure")

    monkeypatch.setattr(booking_dao, "lock_user_for_booking", lock_failure)
    with Session(engine) as db:
        with pytest.raises(HTTPException) as caught:
            booking_service.create_booking(db, request(), 7)
        assert caught.value.status_code == 500
        assert caught.value.detail == "Failed to create reservation"
        assert db.query(Reservation).count() == 0
        assert db.query(Payment).count() == 0


def test_inactive_user_cannot_pass_booking_lock(engine):
    with Session(engine) as db:
        db.get(User, 7).status = "deleted"
        db.commit()
        with pytest.raises(HTTPException) as caught:
            booking_service.create_booking(db, request(), 7)
        assert caught.value.status_code == 401
        assert db.query(Reservation).count() == 0
        assert db.query(Payment).count() == 0


@pytest.mark.parametrize(
    ("second_dates", "expected", "count"),
    [
        ((date(2026, 11, 1), date(2026, 11, 2)), [400, "created"], 1),
        ((date(2026, 11, 2), date(2026, 11, 3)), ["created", "created"], 2),
    ],
)
def test_simulated_concurrent_same_user_attempts(tmp_path, monkeypatch, second_dates, expected, count):
    """SQLite ignores FOR UPDATE; a per-user test lock models the MySQL wait."""
    file_engine = create_engine(f"sqlite:///{tmp_path / 'booking-race.db'}")
    Base.metadata.create_all(file_engine)
    with Session(file_engine) as db:
        db.add(User(user_id=7, email="user7@example.com", password_hash="test"))
        db.commit()

    barrier = Barrier(2)
    guard = Lock()
    original_quote = booking_service.hotel_service.revalidate_hotel
    original_lock = booking_dao.lock_user_for_booking

    def synchronized_quote(info):
        barrier.wait(timeout=5)
        return original_quote(info)

    class GuardedSession(Session):
        held_guard = None

        def release_guard(self):
            if self.held_guard is not None:
                self.held_guard.release()
                self.held_guard = None

        def commit(self):
            try:
                return super().commit()
            finally:
                self.release_guard()

        def rollback(self):
            try:
                return super().rollback()
            finally:
                self.release_guard()

    def simulated_lock(db, user_id):
        assert user_id == 7
        assert guard.acquire(timeout=5)
        db.held_guard = guard
        return original_lock(db, user_id)

    monkeypatch.setattr(booking_service.hotel_service, "revalidate_hotel", synchronized_quote)
    monkeypatch.setattr(booking_dao, "lock_user_for_booking", simulated_lock)

    stays = [
        (date(2026, 11, 1), date(2026, 11, 2)),
        second_dates,
    ]

    def attempt(index):
        with GuardedSession(file_engine) as db:
            try:
                return booking_service.create_booking(
                    db, request(check_in=stays[index][0], check_out=stays[index][1]), 7
                )
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(
        ("created" if isinstance(value, BookingResponse) else value for value in results),
        key=str,
    ) == expected
    with Session(file_engine) as db:
        assert db.query(Reservation).count() == count
        assert db.query(Payment).count() == count
    file_engine.dispose()


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
    for invalid_body in (
        {key: value for key, value in body.items() if key != "guest_full_name"},
        {key: value for key, value in body.items() if key != "guest_email"},
        {**body, "guest_full_name": "   "},
        {**body, "guest_email": "invalid"},
    ):
        assert client.post(
            "/bookings/create", json=invalid_body,
            headers={"Authorization": f"Bearer {user_token}"},
        ).status_code == 422
    with Session(engine) as db:
        assert db.query(Reservation).count() == 0
    response = client.post(
        "/bookings/create", json=body,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "user_id", "hotel_id", "room_type_id", "reservation_id", "payment_id"
    }
    assert response.json()["user_id"] == 7
    overlap = client.post(
        "/bookings/create", json=body,
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert overlap.status_code == 400
    with Session(engine) as db:
        assert db.get(Reservation, response.json()["reservation_id"]).user_id == 7
        assert db.query(Reservation).count() == 1
        assert db.query(Payment).count() == 1
    detail = client.get(
        f"/bookings/get-booking-details/{response.json()['reservation_id']}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["guest_full_name"] == "Person Example"
    assert detail.json()["guest_email"] == "person@example.com"
    other_token = auth.create_access_token(8, subject_type="user")
    non_owner = client.get(
        f"/bookings/get-booking-details/{response.json()['reservation_id']}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert non_owner.status_code == 200
    assert non_owner.json() is None
