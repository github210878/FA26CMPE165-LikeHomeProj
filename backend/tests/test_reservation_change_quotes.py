"""Quote-only API/security tests; SQLite and a mocked provider, no live services."""

from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.repositories import booking_dao
from app.routers.booking_router import router
from app.schemas.hotel_schema import HotelRevalidationResponse
from app.schemas.reservation_change_schema import (
    ReservationChangeConfirmRequest, ReservationChangeReviewRequest, ReservationChangeRevalidationContext,
)
from app.services import reservation_change_service
from app.services.reservation_change_validation import build_change_revalidation_request
from app.utilities import auth, reservation_change_quote, serpapi_client

NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
PATH = "/bookings/1/change-quote"
REQUEST = {
    "check_in_date": "2026-11-04", "check_out_date": "2026-11-06",
    "q": " San Jose hotels ", "adults": 3, "children": 1,
}


@pytest.fixture
def quote_app(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            User(user_id=7, email="owner@example.test", password_hash="test", status="active", reward_points=0),
            User(user_id=8, email="other@example.test", password_hash="test", status="active"),
            Hotel(hotel_id=1, name="Hotel A", hotel_token="property-A"),
            Hotel(hotel_id=2, name="Hotel B", hotel_token="property-B"),
            RoomType(room_type_id=1, hotel_id=1, type_name="Lowest available rate", price_per_night=100),
            RoomType(room_type_id=2, hotel_id=2, type_name="Lowest available rate", price_per_night=100),
            Reservation(reservation_id=1, user_id=7, room_type_id=1,
                        check_in_date=date(2026, 11, 1), check_out_date=date(2026, 11, 3),
                        status="confirmed", total_price=210),
            Payment(payment_id=1, reservation_id=1, amount=226.80,
                    payment_type="booking", payment_status="pending"),
        ])
        db.commit()

    calls = []
    provider_state = {"error": None, "unavailable": False, "wrong_property": False}

    def provider(params):
        calls.append(params.copy())
        if provider_state["error"] is not None:
            raise provider_state["error"]
        nights = (date.fromisoformat(params["check_out_date"]) - date.fromisoformat(params["check_in_date"])).days
        return {
            "name": "Hotel A",
            "property_token": "property-B" if provider_state["wrong_property"] else params["property_token"],
            "prices": [] if provider_state["unavailable"] else [
                {"source": source, "num_guests": 4,
                 "rate_per_night": {"extracted_before_taxes_fees": nightly},
                 "total_rate": {"extracted_before_taxes_fees": nightly * nights,
                                "extracted_lowest": (nightly + 10) * nights}}
                for source, nightly in [("Expensive provider", 120), ("Trusted provider", 80)]
            ],
        }

    monkeypatch.setattr(serpapi_client, "search_google_hotels", provider)
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "isolated-change-quote-secret-at-least-32-bytes")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as client:
        yield client, engine, calls, provider_state
    engine.dispose()


def headers(user_id=7, subject_type="user"):
    return {"Authorization": f"Bearer {auth.create_access_token(user_id, subject_type=subject_type)}"}


def quote(client, **changes):
    return client.post(PATH, headers=headers(), json={**REQUEST, **changes})


def load(engine):
    with Session(engine) as db:
        return booking_dao.get_owned_reservation_for_change(db, 1, 7)


def info(records, **changes):
    reservation, room, hotel, _ = records
    request = ReservationChangeReviewRequest(**{**REQUEST, **changes})
    context = ReservationChangeRevalidationContext(**request.model_dump(exclude={"check_in_date", "check_out_date"}))
    return build_change_revalidation_request(reservation, room, hotel, request, context)


def verify(token, records, *, user_id=7, context=None, now=NOW):
    reservation, room, hotel, payments = records
    return reservation_change_quote.verify_reservation_change_quote(
        token, reservation=reservation, room_type=room, hotel=hotel,
        payments=payments, user_id=user_id, context=context or info(records), now=now,
    )


def fixed_review(quote_app):
    client, engine, _, _ = quote_app
    data = quote(client).json()
    records = load(engine)
    trusted_quote = HotelRevalidationResponse(**data["quote"])
    reservation, room, hotel, payments = records
    response = reservation_change_quote.issue_reservation_change_quote(
        reservation=reservation, room_type=room, hotel=hotel, payment=payments[0],
        user_id=7, context=info(records), quote=trusted_quote, now=NOW,
    )
    return response, records


def resigned(token, changes=None, *, remove=None, algorithm=None, key=None, header_type=None):
    payload = jwt.decode(token, options={"verify_signature": False})
    payload.update(changes or {})
    if remove:
        payload.pop(remove)
    configured_key, configured_algorithm = reservation_change_quote._signing_parameters()
    return jwt.encode(
        payload, key or configured_key, algorithm=algorithm or configured_algorithm,
        headers={"typ": header_type or reservation_change_quote.QUOTE_HEADER_TYPE},
    )


@pytest.mark.parametrize("status", ["pending", "paid"])
def test_owner_reviews_trusted_prices_for_paid_or_unpaid_stay(quote_app, status):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = status
        db.commit()
    response = quote(client)
    assert response.status_code == 200
    data = response.json()
    assert data["reservation_id"] == 1
    assert data["quote"]["property_token"] == "property-A"
    assert data["quote"]["source"] == "Trusted provider"
    assert data["quote"]["current_price_per_night"] == 80
    assert data["quote"]["provider_base_total"] == 160
    assert data["quote"]["likehome_reservation_total"] == 168
    assert data["quote"]["likehome_payment_amount"] == 181.44
    assert len(calls) == 1
    assert calls[0] == {
        "property_token": "property-A", "q": "San Jose hotels",
        "check_in_date": REQUEST["check_in_date"], "check_out_date": REQUEST["check_out_date"],
        "adults": 3, "children": 1, "currency": "USD", "gl": "us", "hl": "en",
    }
    verified = verify(data["quote_id"], load(engine), now=datetime.now(timezone.utc))
    assert verified.model_dump(mode="json") == data
    # The signed token fits the existing future acceptance contract.
    acceptance = ReservationChangeConfirmRequest(
        check_in_date=REQUEST["check_in_date"], check_out_date=REQUEST["check_out_date"],
        quote_id=data["quote_id"], accept_quote=True, price_per_night=80, accepted_payment_amount=181.44,
    )
    assert acceptance.quote_id == verified.quote_id


@pytest.mark.parametrize("path,user_id", [(PATH, 8), ("/bookings/999/change-quote", 7)])
def test_nonowner_and_missing_reservation_are_indistinguishable(quote_app, path, user_id):
    client, engine, calls, _ = quote_app
    response = client.post(path, headers=headers(user_id), json=REQUEST)
    assert response.status_code == 404
    assert response.json() == {"detail": "Reservation not found"}
    assert calls == []
    with Session(engine) as db:
        assert booking_dao.get_owned_reservation_for_change(db, 1, 8) is None


@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic invalid", "partner"])
def test_missing_invalid_and_partner_authentication_are_rejected(quote_app, authorization):
    client, _, calls, _ = quote_app
    auth_headers = headers(subject_type="partner") if authorization == "partner" else (
        {} if authorization is None else {"Authorization": authorization}
    )
    response = client.post(PATH, headers=auth_headers, json=REQUEST)
    assert response.status_code == 401
    assert calls == []


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_ineligible_reservation_statuses_do_not_call_provider(quote_app, status):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.get(Reservation, 1).status = status
        db.commit()
    assert quote(client).status_code == 409
    assert calls == []


@pytest.mark.parametrize("check_in", [date(2026, 9, 28), date(2026, 9, 29)])
def test_past_and_started_reservations_are_rejected(quote_app, check_in):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.get(Reservation, 1).check_in_date = check_in
        db.commit()
    assert quote(client).status_code == 409
    assert calls == []


@pytest.mark.parametrize("case", ["failed", "refunded", "missing", "duplicate", "cancellation"])
def test_unsupported_or_ambiguous_payments_are_rejected(quote_app, case):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        payment = db.get(Payment, 1)
        if case == "missing":
            db.delete(payment)
        elif case == "duplicate":
            db.add(Payment(reservation_id=1, amount=226.80, payment_type="booking", payment_status="paid"))
        elif case == "cancellation":
            payment.payment_type = "cancellation"
        else:
            payment.payment_status = case
        db.commit()
    assert quote(client).status_code == 409
    assert calls == []


@pytest.mark.parametrize("field", ["q", "adults", "children", "check_in_date", "check_out_date"])
def test_review_requires_reconfirmed_context_and_dates(quote_app, field):
    client, _, calls, _ = quote_app
    request = {key: value for key, value in REQUEST.items() if key != field}
    assert client.post(PATH, headers=headers(), json=request).status_code == 422
    assert calls == []


@pytest.mark.parametrize("changes", [
    {"q": " "}, {"adults": 0}, {"adults": 21}, {"adults": True},
    {"children": -1}, {"children": 21}, {"children": "0"},
    {"property_token": "property-B"}, {"hotel_id": 2}, {"user_id": 8},
    {"price_per_night": 1}, {"accepted_payment_amount": 1},
    {"currency": "EUR"}, {"gl": "gb"}, {"hl": "fr"},
    {"check_in_date": "2026-02-30"}, {"check_out_date": "2026-11-04"},
])
def test_invalid_context_or_client_authority_fields_are_rejected(quote_app, changes):
    client, _, calls, _ = quote_app
    assert quote(client, **changes).status_code == 422
    assert calls == []


def test_reconfirmed_context_does_not_claim_original_occupancy_or_change_hotels(quote_app):
    client, _, calls, _ = quote_app
    response = quote(client, q="A newly reconfirmed destination", adults=1, children=0)
    assert response.status_code == 200
    assert calls[0]["q"] == "A newly reconfirmed destination"
    assert response.json()["quote"]["adults"] == 1
    assert response.json()["quote"]["property_token"] == "property-A"


@pytest.mark.parametrize("case", ["missing-room", "missing-hotel", "legacy", "partner", "empty"])
def test_missing_or_unsupported_property_identity_is_rejected(quote_app, case):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        if case == "missing-room":
            db.get(Reservation, 1).room_type_id = 999
        elif case == "missing-hotel":
            db.get(RoomType, 1).hotel_id = 999
        else:
            db.get(Hotel, 1).hotel_token = {"legacy": "legacy:1", "partner": "partner:1", "empty": ""}[case]
        db.commit()
    assert quote(client).status_code == 409
    assert calls == []


def test_current_reservation_is_excluded_but_creation_overlap_behavior_is_preserved(quote_app):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        assert booking_dao.check_if_user_booked_by_date_range(db, 7, date(2026, 11, 2), date(2026, 11, 4))
        assert not booking_dao.check_if_user_booked_by_date_range(
            db, 7, date(2026, 11, 2), date(2026, 11, 4), exclude_reservation_id=1,
        )
    assert quote(client, check_in_date="2026-11-02", check_out_date="2026-11-04").status_code == 200
    assert len(calls) == 1


def test_unchanged_dates_are_rejected_before_provider_call(quote_app):
    client, _, calls, _ = quote_app
    assert quote(client, check_in_date="2026-11-01", check_out_date="2026-11-03").status_code == 422
    assert calls == []


@pytest.mark.parametrize("room_id", [1, 2])
@pytest.mark.parametrize("status", ["confirmed", "completed"])
def test_same_user_conflict_blocks_quotes_at_same_or_different_hotels(quote_app, room_id, status):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.add(Reservation(user_id=7, room_type_id=room_id,
                           check_in_date=date(2026, 11, 5), check_out_date=date(2026, 11, 7),
                           total_price=210, status=status))
        db.commit()
    assert quote(client).status_code == 400
    assert calls == []


@pytest.mark.parametrize("check_in,check_out,status,user_id", [
    (date(2026, 11, 2), date(2026, 11, 4), "confirmed", 7),
    (date(2026, 11, 6), date(2026, 11, 8), "confirmed", 7),
    (date(2026, 11, 4), date(2026, 11, 6), "cancelled", 7),
    (date(2026, 11, 4), date(2026, 11, 6), "confirmed", 8),
])
def test_adjacent_cancelled_and_other_user_stays_do_not_block(quote_app, check_in, check_out, status, user_id):
    client, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.add(Reservation(user_id=user_id, room_type_id=2, check_in_date=check_in,
                           check_out_date=check_out, total_price=210, status=status))
        db.commit()
    assert quote(client).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("failure,expected", [("unavailable", 409), ("wrong_property", 409), ("network", 502), ("timeout", 504)])
def test_provider_failures_propagate_without_old_price_fallback(quote_app, failure, expected):
    client, _, calls, provider_state = quote_app
    if failure == "network":
        provider_state["error"] = serpapi_client.SerpApiRequestError("isolated network failure")
    elif failure == "timeout":
        provider_state["error"] = serpapi_client.SerpApiTimeoutError("isolated timeout")
    else:
        provider_state[failure] = True
    response = quote(client)
    assert response.status_code == expected
    assert "quote_id" not in response.json()
    assert len(calls) == 1


def test_signed_review_has_exact_ten_minute_utc_lifetime(quote_app):
    response, records = fixed_review(quote_app)
    assert response.expires_at == NOW + timedelta(minutes=10)
    assert response.expires_at.tzinfo == timezone.utc
    assert verify(response.quote_id, records).quote == response.quote
    for now in (NOW + timedelta(minutes=10), NOW + timedelta(minutes=11), NOW - timedelta(seconds=1)):
        with pytest.raises(HTTPException) as error:
            verify(response.quote_id, records, now=now)
        assert error.value.status_code == 409


def test_quote_tokens_cannot_be_used_as_access_tokens_or_vice_versa(quote_app):
    client, _, _, _ = quote_app
    response, records = fixed_review(quote_app)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=response.quote_id)
    with pytest.raises(HTTPException) as error:
        auth.decode_access_token(credentials)
    assert error.value.status_code == 401
    assert client.post(PATH, headers={"Authorization": f"Bearer {response.quote_id}"}, json=REQUEST).status_code == 401
    with pytest.raises(HTTPException):
        verify(auth.create_access_token(7, subject_type="user"), records)


def test_quote_clock_is_aware_and_non_utc_clock_is_normalized(quote_app):
    response, records = fixed_review(quote_app)
    pacific = NOW.astimezone(timezone(timedelta(hours=-7)))
    assert verify(response.quote_id, records, now=pacific).expires_at == response.expires_at
    with pytest.raises(ValueError, match="timezone-aware"):
        verify(response.quote_id, records, now=NOW.replace(tzinfo=None))


def test_issuer_refuses_context_for_a_replacement_property(quote_app):
    response, records = fixed_review(quote_app)
    reservation, room, hotel, payments = records
    replacement_context = info(records).model_copy(update={"property_token": "property-B"})
    replacement_quote = response.quote.model_copy(update={"property_token": "property-B"})
    with pytest.raises(HTTPException) as error:
        reservation_change_quote.issue_reservation_change_quote(
            reservation=reservation, room_type=room, hotel=hotel, payment=payments[0],
            user_id=7, context=replacement_context, quote=replacement_quote, now=NOW,
        )
    assert error.value.status_code == 409


@pytest.mark.parametrize("case", ["signature", "body", "algorithm", "header-type", "wrong-key", "garbage", "oversized"])
def test_tampered_or_unsupported_tokens_are_rejected(quote_app, case):
    response, records = fixed_review(quote_app)
    token = response.quote_id
    if case == "signature":
        head, body, signature = token.split(".")
        token = f"{head}.{body}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    elif case == "body":
        other = resigned(token, {"sub": "8"})
        token = ".".join([*other.split(".")[:2], token.split(".")[2]])
    elif case == "algorithm":
        token = resigned(token, algorithm="HS384")
    elif case == "header-type":
        token = resigned(token, header_type="JWT")
    elif case == "wrong-key":
        token = resigned(token, key=b"unrelated-test-key-of-at-least-32-bytes")
    elif case == "garbage":
        token = "not-a-quote"
    else:
        token = "x" * (reservation_change_quote.MAX_CHANGE_QUOTE_LENGTH + 1)
    with pytest.raises(HTTPException) as error:
        verify(token, records)
    assert error.value.status_code == 409


@pytest.mark.parametrize("changes", [
    {"type": "user"}, {"version": 3}, {"version": True}, {"aud": "other"}, {"iss": "other"},
    {"iat": True}, {"exp": 1}, {"reservation_id": "1"}, {"unexpected": "field"},
])
def test_wrong_purpose_or_malformed_signed_claims_are_rejected(quote_app, changes):
    response, records = fixed_review(quote_app)
    with pytest.raises(HTTPException) as error:
        verify(resigned(response.quote_id, changes), records)
    assert error.value.status_code == 409


@pytest.mark.parametrize("field", ["type", "iat", "exp", "context", "quote", "state_fingerprint"])
def test_required_security_claims_cannot_be_omitted(quote_app, field):
    response, records = fixed_review(quote_app)
    with pytest.raises(HTTPException) as error:
        verify(resigned(response.quote_id, remove=field), records)
    assert error.value.status_code == 409


def test_wrong_owner_reservation_and_hotel_are_rejected(quote_app):
    response, records = fixed_review(quote_app)
    with pytest.raises(HTTPException):
        verify(response.quote_id, records, user_id=8)
    reservation, room, hotel, payments = records
    reservation.reservation_id = 999
    with pytest.raises(HTTPException):
        verify(response.quote_id, records)
    reservation.reservation_id = 1
    hotel.hotel_id = 999
    with pytest.raises(HTTPException):
        verify(response.quote_id, records, context=info(load(quote_app[1])))


@pytest.mark.parametrize("changes", [
    {"q": "Another destination"}, {"adults": 2}, {"children": 0},
    {"check_in_date": "2026-11-05"}, {"check_out_date": "2026-11-07"},
])
def test_quote_cannot_be_reused_for_different_dates_or_reconfirmed_context(quote_app, changes):
    response, records = fixed_review(quote_app)
    with pytest.raises(HTTPException) as error:
        verify(response.quote_id, records, context=info(records, **changes))
    assert error.value.status_code == 409


@pytest.mark.parametrize("model,field,value", [
    (Reservation, "check_out_date", date(2026, 11, 4)),
    (Reservation, "total_price", 220), (Reservation, "guest_full_name", "Changed guest"),
    (Payment, "payment_status", "paid"), (Payment, "amount", 240),
    (RoomType, "price_per_night", 110), (Hotel, "hotel_token", "property-B-new"),
])
def test_changed_original_reservation_payment_or_property_state_invalidates_review(quote_app, model, field, value):
    response, _ = fixed_review(quote_app)
    engine = quote_app[1]
    with Session(engine) as db:
        setattr(db.get(model, 1), field, value)
        db.commit()
    records = load(engine)
    with pytest.raises(HTTPException) as error:
        verify(response.quote_id, records, context=info(records))
    assert error.value.status_code == 409


def test_added_booking_payment_invalidates_review(quote_app):
    response, _ = fixed_review(quote_app)
    engine = quote_app[1]
    with Session(engine) as db:
        db.add(Payment(reservation_id=1, amount=10, payment_type="booking", payment_status="pending"))
        db.commit()
    with pytest.raises(HTTPException) as error:
        verify(response.quote_id, load(engine))
    assert error.value.status_code == 409


@pytest.mark.parametrize("secret,algorithm", [(None, "HS256"), ("short", "HS256"), ("x" * 32, "none")])
def test_unsafe_signing_configuration_fails_before_provider_call(quote_app, monkeypatch, secret, algorithm):
    _, engine, calls, _ = quote_app
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", secret)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", algorithm)
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            reservation_change_service.quote_reservation_change(db, ReservationChangeReviewRequest(**REQUEST), 1, 7)
    assert error.value.status_code == 500
    assert calls == []


def test_quote_and_verification_remain_read_only(quote_app):
    client, engine, calls, _ = quote_app

    def snapshot():
        with Session(engine) as db:
            return {
                model.__tablename__: [
                    {column.name: getattr(row, column.name) for column in model.__table__.columns}
                    for row in db.scalars(select(model).order_by(list(model.__table__.primary_key.columns)[0]))
                ]
                for model in (User, Hotel, RoomType, Reservation, Payment)
            }

    before = snapshot()
    statements = []

    def record_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(engine, "before_cursor_execute", record_statement)
    response = quote(client)
    assert response.status_code == 200
    verify(response.json()["quote_id"], load(engine), now=datetime.now(timezone.utc))
    assert snapshot() == before
    assert not {"UPDATE", "INSERT", "DELETE"}.intersection(statements)
    assert len(calls) == 1
    assert client.post("/bookings/1/change-confirm", headers=headers(), json=REQUEST).status_code == 422
