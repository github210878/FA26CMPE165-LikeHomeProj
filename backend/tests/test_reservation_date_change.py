"""Date changes against a disposable DB and the actual mocked-provider pricing path."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.config.database import Base, get_db
from app.main import app
from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.services import hotel_service
from app.utilities import auth

OLD_DATES = {"check_in_date": "2027-02-01", "check_out_date": "2027-02-03"}
NEW_DATES = {"check_in_date": "2027-02-02", "check_out_date": "2027-02-04"}
CHANGE = "/bookings/1/change-dates"
PROPERTY = "property-56b"


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'date-change.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(user_id=i, email=f"guest{i}@example.com", password_hash="fixture") for i in (1, 2)])
        db.commit()

    sessions = []

    def local_session():
        with Session(engine, autoflush=False) as db:
            sessions.append(db)
            yield db

    def headers(uid):
        return {"Authorization": f"Bearer {auth.create_access_token(uid, subject_type='user')}"}

    calls = []
    provider = {"inclusive": 270.0, "token": PROPERTY, "capacity": 4}

    def details(params):
        calls.append(params)
        original = params["check_in_date"] == OLD_DATES["check_in_date"]
        if not original:
            assert not sessions[-1].in_transaction()
        return {
            "name": "Original hotel",
            "property_token": provider["token"],
            "prices": [{
                "source": "Mock provider", "num_guests": provider["capacity"],
                "rate_per_night": {"extracted_before_taxes_fees": 120},
                "total_rate": {
                    "extracted_before_taxes_fees": 240,
                    "extracted_lowest": 300 if original else provider["inclusive"],
                },
            }],
        }

    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "date-change-isolated-test-signing-key")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    monkeypatch.setitem(app.dependency_overrides, get_db, local_session)
    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", details)

    with TestClient(app) as client:
        booked = client.post("/bookings/create", headers=headers(1), json={
            **OLD_DATES, "hotel_token": PROPERTY, "q": "Original city",
            "adults": 3, "children": 1, "guest_full_name": "Original Guest",
            "guest_email": "guest@example.com", "price_per_night": 150, "accepted_payment_amount": 340.20,
        })
        assert booked.status_code == 200
        assert booked.json()["reservation_id"] == 1
        yield client, headers, engine, calls, provider
    engine.dispose()


def records(engine):
    with Session(engine) as db:
        reservation = db.get(Reservation, 1)
        payment = db.get(Payment, 1)
        room = db.get(RoomType, reservation.room_type_id)
        return (
            reservation.check_in_date, reservation.check_out_date, reservation.total_price,
            payment.amount, reservation.booking_context, reservation.user_id, room.room_type_id,
            room.price_per_night, reservation.guest_full_name, reservation.guest_email,
            payment.payment_status,
        )


def test_save_and_reload_with_provider_total_and_unchanged_identity(scenario):
    client, headers, engine, calls, _ = scenario
    response = client.post(CHANGE, headers=headers(1), json=NEW_DATES)
    assert response.status_code == 200, response.text
    assert response.json() == {
        **NEW_DATES, "reservation_id": 1, "booking_reference": "LH-00000001", "payment_id": 1,
        "total_price": 283.50, "payment_amount": 306.18, "changed": True,
    }
    assert calls[-1] == {
        **NEW_DATES, "q": "Original city", "property_token": PROPERTY, "adults": 3, "children": 1,
        "currency": "USD", "gl": "us", "hl": "en",
    }
    after = records(engine)
    assert after[:4] == (date(2027, 2, 2), date(2027, 2, 4), 283.50, 306.18)
    assert after[4]["pending_amount"] == "306.18"
    assert after[5:] == (1, 1, 150, "Original Guest", "guest@example.com", "pending")

    listing = client.get("/bookings/get-all-bookings", headers=headers(1)).json()
    detail = client.get("/bookings/get-booking-details/1", headers=headers(1)).json()
    assert listing[0]["check_in_date"] == NEW_DATES["check_in_date"]
    assert (detail["check_out_date"], detail["price_per_night"], detail["total_price"]) == (
        NEW_DATES["check_out_date"], 135, 283.50,
    )

    replay = client.post(CHANGE, headers=headers(1), json=NEW_DATES)
    assert replay.json() == {**response.json(), "changed": False}
    assert len(calls) == 2
    with Session(engine) as db:
        assert len(db.scalars(select(Reservation)).all()) == 1
        assert len(db.scalars(select(Payment)).all()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"check_in_date": "2027-02-30"}, {"check_in_date": "20270202"},
        {"check_in_date": "2027-02-02T00:00:00"}, {"check_in_date": 1801526400},
        {"check_in_date": "2020-01-01"}, {"check_out_date": NEW_DATES["check_in_date"]},
        {"check_out_date": "2027-02-01"}, {"user_id": 2}, {"guest_email": "replacement@example.com"},
        {"hotel_token": "another-hotel"}, {"price": 1}, {"adults": 4},
    ],
)
def test_rejects_invalid_dates_and_unexpected_fields(scenario, changes):
    client, headers, engine, calls, _ = scenario
    before = records(engine)
    assert client.post(CHANGE, headers=headers(1), json={**NEW_DATES, **changes}).status_code == 422
    assert records(engine) == before and len(calls) == 1


def test_authentication_and_ownership(scenario):
    client, headers, engine, calls, _ = scenario
    before = records(engine)
    assert client.post(CHANGE, json=NEW_DATES).status_code == 401
    assert client.post(CHANGE, headers=headers(2), json=NEW_DATES).status_code == 404
    assert records(engine) == before and len(calls) == 1


@pytest.mark.parametrize(
    ("owner", "other_hotel", "status", "start", "end", "blocked"),
    [
        (1, False, "confirmed", 3, 5, True),
        (1, True, "confirmed", 3, 5, True),
        (1, True, "completed", 3, 5, True),
        (1, True, "cancelled", 3, 5, False),
        (2, True, "confirmed", 3, 5, False),
        (1, True, "confirmed", 4, 5, False),
    ],
)
def test_overlap_uses_create_booking_rules(scenario, owner, other_hotel, status, start, end, blocked):
    client, headers, engine, _, _ = scenario
    with Session(engine) as db:
        if other_hotel:
            db.add(Hotel(hotel_id=2, name="Other hotel", hotel_token="property-other"))
            db.add(RoomType(room_type_id=2, hotel_id=2, type_name="Other room", price_per_night=80))
        db.add(Reservation(user_id=owner, room_type_id=2 if other_hotel else 1,
                           check_in_date=date(2027, 2, start), check_out_date=date(2027, 2, end),
                           status=status, total_price=100))
        db.commit()
    before = records(engine)
    response = client.post(CHANGE, headers=headers(1), json=NEW_DATES)
    if blocked:
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "dates_overlap"}
        assert records(engine) == before
    else:
        assert response.status_code == 200, response.text
        assert response.json()["changed"] is True


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("legacy", "booking_context_missing"), ("cancelled", "reservation_not_confirmed"),
        ("paid", "payment_unsupported"), ("points_paid", "payment_unsupported"),
        ("balance_applied", "payment_unsupported"), ("refunded", "payment_unsupported"),
    ],
)
def test_unsupported_stays_fail_before_provider(scenario, change, code):
    client, headers, engine, calls, _ = scenario
    with Session(engine) as db:
        reservation, payment = db.get(Reservation, 1), db.get(Payment, 1)
        if change == "legacy":
            reservation.booking_context = None
        elif change == "cancelled":
            reservation.status = "cancelled"
        elif change == "balance_applied":
            payment.amount = 320.20
        elif change == "points_paid":
            from app.models.redeem_history import RedeemHistory

            payment.payment_status = "paid"
            db.add(RedeemHistory(user_id=1, redemption_type="free_stay", payment_id=1,
                                 reservation_id=1, reward_points_redeemed=34020))
        else:
            payment.payment_status = change
        db.commit()
    before = records(engine)
    response = client.post(CHANGE, headers=headers(1), json=NEW_DATES)
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": code}
    assert records(engine) == before and len(calls) == 1


@pytest.mark.parametrize(("field", "value", "status"), [
    ("inclusive", 310, 409), ("inclusive", None, 502),
    ("capacity", 3, 409), ("token", "other-property", 409),
])
def test_quote_cannot_increase_obligation_or_skip_availability(scenario, field, value, status):
    client, headers, engine, _, provider = scenario
    provider[field] = value
    before = records(engine)
    response = client.post(CHANGE, headers=headers(1), json=NEW_DATES)
    assert response.status_code == status, response.text
    if value == 310:
        assert response.json()["detail"] == {"code": "price_increase"}
    assert records(engine) == before


def test_equal_quote_saves_dates_without_changing_the_pending_amount(scenario):
    client, headers, engine, _, provider = scenario
    provider["inclusive"] = 300
    before = records(engine)
    result = client.post(CHANGE, headers=headers(1), json=NEW_DATES)
    assert result.status_code == 200, result.text
    assert result.json()["changed"] is True
    after = records(engine)
    assert after[:2] == (date(2027, 2, 2), date(2027, 2, 4))
    assert after[2:] == before[2:]


def test_legacy_create_defaults_are_not_saved_as_original_guest_details(scenario):
    client, headers, engine, _, _ = scenario
    booked = client.post("/bookings/create", headers=headers(2), json={
        **OLD_DATES, "hotel_token": PROPERTY, "q": "Original city",
        "guest_full_name": "Second Guest", "guest_email": "second@example.com",
        "price_per_night": 150, "accepted_payment_amount": 340.20,
    })
    assert booked.status_code == 200, booked.text
    reservation_id = booked.json()["reservation_id"]
    with Session(engine) as db:
        assert db.get(Reservation, reservation_id).booking_context is None
    change = client.post(f"/bookings/{reservation_id}/change-dates", headers=headers(2), json=NEW_DATES)
    assert change.status_code == 409
    assert change.json()["detail"] == {"code": "booking_context_missing"}


def test_provider_timeout_does_not_mutate(scenario, monkeypatch):
    client, headers, engine, _, _ = scenario
    before = records(engine)

    def fail(_):
        from app.utilities.serpapi_client import SerpApiTimeoutError

        raise SerpApiTimeoutError("synthetic provider timeout")

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", fail)
    assert client.post(CHANGE, headers=headers(1), json=NEW_DATES).status_code == 504
    assert records(engine) == before


def test_concurrent_payment_state_rechecked_after_quote(scenario, monkeypatch):
    client, headers, engine, _, _ = scenario
    provider = hotel_service.serpapi_client.search_google_hotels

    def pay_while_quoting(params):
        quote = provider(params)
        with Session(engine) as db:
            db.get(Payment, 1).payment_status = "paid"
            db.commit()
        return quote

    monkeypatch.setattr(hotel_service.serpapi_client, "search_google_hotels", pay_while_quoting)
    before = records(engine)
    response = client.post(CHANGE, headers=headers(1), json=NEW_DATES)
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "payment_unsupported"}
    assert records(engine) == (*before[:-1], "paid")


def test_commit_failure_rolls_back_dates_and_payment(scenario):
    client, headers, engine, _, _ = scenario
    before = records(engine)

    def fail_payment_write(conn, cursor, statement, *args):
        if statement.startswith("UPDATE payments"):
            raise RuntimeError("synthetic payment write failure")

    event.listen(engine, "before_cursor_execute", fail_payment_write)
    try:
        assert client.post(CHANGE, headers=headers(1), json=NEW_DATES).status_code == 500
    finally:
        event.remove(engine, "before_cursor_execute", fail_payment_write)
    assert records(engine) == before
