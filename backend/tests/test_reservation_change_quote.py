"""Quote-only HTTP/security tests: synthetic SQLite and mocked provider only.

Run through the offline guard used for booking/payment tests. These tests prove
read-only API behavior, not MySQL concurrency or confirmation correctness.
"""

import base64
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.repositories import booking_dao, reservation_change_quote_dao
from app.routers.booking_router import router
from app.schemas.reservation_change_schema import ReservationChangeQuoteResponse, ReservationChangeReviewRequest
from app.services import booking_service, hotel_service, reservation_change_quote_service as service
from app.utilities import auth, serpapi_client
from app.utilities.serpapi_client import (
    SerpApiConfigError, SerpApiRequestError, SerpApiResponseError, SerpApiTimeoutError,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
AUTH_SECRET = "synthetic-quote-auth-root-key-at-least-32-bytes"
REVIEW_SECRET = "synthetic-quote-review-root-key-at-least-32-bytes"


def review(**changes):
    return {"check_in_date": "2026-11-10", "check_out_date": "2026-11-12",
            "q": "Synthetic destination", "adults": 2, "children": 1, **changes}


def headers(user_id=7, role="user"):
    return {"Authorization": "Bearer " + auth.create_access_token(user_id, subject_type=role)}


def database_state(engine):
    """Compare every persisted value in every registered table, not just counts."""
    with engine.connect() as connection:
        return {table.name: [tuple(row) for row in connection.execute(
            select(table).order_by(*table.primary_key.columns)
        )] for table in Base.metadata.sorted_tables}


@pytest.fixture
def quote_app(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            User(user_id=7, email="owner@example.test", password_hash="synthetic-hash",
                 status="active", reward_points=37, session_version=0),
            User(user_id=8, email="other@example.test", password_hash="synthetic-hash",
                 status="active", reward_points=19, session_version=0),
            Hotel(hotel_id=1, name="Stored hotel", hotel_token="synthetic-property-A"),
            RoomType(room_type_id=1, hotel_id=1, type_name="Original room", price_per_night=100),
            Reservation(reservation_id=1, user_id=7, room_type_id=1,
                        guest_full_name="Synthetic Guest", guest_email="guest@example.test",
                        check_in_date=date(2026, 11, 1), check_out_date=date(2026, 11, 3),
                        total_price=210, status="confirmed"),
            Payment(payment_id=1, reservation_id=1, amount=226.80,
                    payment_type="booking", payment_status="pending"),
        ])
        db.commit()

    calls, sql, sessions = [], [], []

    def provider(params):
        calls.append(dict(params))
        return {"property_token": params["property_token"], "name": "Revalidated hotel",
                "prices": [{"source": "Synthetic provider", "num_guests": 4,
                            "rate_per_night": {"extracted_before_taxes_fees": 120},
                            "total_rate": {"extracted_before_taxes_fees": 240, "extracted_lowest": 270}}]}

    monkeypatch.setattr(serpapi_client, "search_google_hotels", provider)
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", AUTH_SECRET)
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(service.Config, "JWT_SECRET_KEY", REVIEW_SECRET)
    monkeypatch.setattr(service.Config, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(service, "_now", lambda: NOW)

    def forbidden(*args, **kwargs):
        pytest.fail("Quote attempted a write/financial operation")

    for name in ("create_booking", "pay_booking_payment", "cancel_booking"):
        monkeypatch.setattr(booking_service, name, forbidden)
    monkeypatch.setattr(booking_dao, "add_reward_points_to_user", forbidden)

    def only_select(connection, cursor, statement, parameters, context, many):
        assert statement.lstrip().upper().startswith("SELECT"), "Quote attempted non-SELECT SQL"
        assert "FOR UPDATE" not in statement.upper()
        sql.append(statement)

    def isolated_db():
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA query_only=ON")
            event.listen(connection, "before_cursor_execute", only_select)
            try:
                with Session(bind=connection, autoflush=False) as db:
                    monkeypatch.setattr(db, "commit", forbidden)
                    monkeypatch.setattr(db, "flush", forbidden)
                    yield db
                    sessions.append((len(db.new), len(db.dirty), len(db.deleted)))
            finally:
                event.remove(connection, "before_cursor_execute", only_select)
                connection.exec_driver_sql("PRAGMA query_only=OFF")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as client:
        def post(body=None, *, request_headers=None, reservation_id=1):
            before = database_state(engine)
            response = client.post(f"/bookings/{reservation_id}/change-quote",
                                   json=review() if body is None else body,
                                   headers=headers() if request_headers is None else request_headers)
            assert database_state(engine) == before
            assert all(state == (0, 0, 0) for state in sessions)
            return response
        yield SimpleNamespace(client=client, engine=engine, post=post, calls=calls, sql=sql)
    engine.dispose()


def change_record(app, model, identity=1, **changes):
    with Session(app.engine) as db:
        record = db.get(model, identity)
        for field, value in changes.items():
            setattr(record, field, value)
        db.commit()


def verified(response, **changes):
    return service.verify_review_acknowledgement(response["quote_id"],
                                               **{"user_id": 7, "reservation_id": 1, **changes})


@pytest.mark.parametrize("payment_status", ["pending", "paid"])
def test_owner_receives_provider_quote_and_typed_response_without_writes(quote_app, payment_status):
    change_record(quote_app, Payment, payment_status=payment_status)
    result = quote_app.post(review(q="  Reconfirmed city  ", adults=3, children=1))
    assert result.status_code == 200
    body = result.json()
    assert set(body) == {"reservation_id", "quote_id", "expires_at", "quote"}
    assert ReservationChangeQuoteResponse.model_validate(body).model_dump(mode="json") == body
    assert quote_app.calls == [{"q": "Reconfirmed city", "property_token": "synthetic-property-A",
                                "check_in_date": "2026-11-10", "check_out_date": "2026-11-12",
                                "adults": 3, "children": 1, "currency": "USD", "gl": "us", "hl": "en"}]
    quote = body["quote"]
    assert quote["hotel_name"] == "Revalidated hotel"
    assert quote["current_price_per_night"] == 120
    assert quote["provider_base_total"] == 240
    assert quote["provider_total_with_taxes_fees"] == 270
    assert quote["likehome_reservation_total"] == 252
    assert quote["likehome_payment_amount"] == 272.16
    assert quote["price_changed"] is None
    claims = verified(body)
    assert claims["review"] == {**review(q="Reconfirmed city", adults=3), "currency": "USD", "gl": "us", "hl": "en"}
    assert claims["quote"] == quote
    assert claims["snapshot"]["booking_payment_status"] == payment_status
    assert claims["snapshot"]["reservation_total"] == "210.00"
    assert claims["snapshot"]["booking_payment_amount"] == "226.80"
    assert len(quote_app.sql) == 2  # Authentication and one owner-scoped joined projection.


def test_changed_dates_revalidate_property_without_mutating_original_reservation(quote_app):
    requested = review(check_in_date="2026-11-10", check_out_date="2026-11-12")
    result = quote_app.post(requested)

    assert result.status_code == 200
    assert quote_app.calls == [{
        "q": "Synthetic destination",
        "property_token": "synthetic-property-A",
        "check_in_date": "2026-11-10",
        "check_out_date": "2026-11-12",
        "adults": 2,
        "children": 1,
        "currency": "USD",
        "gl": "us",
        "hl": "en",
    }]
    assert result.json()["quote"]["check_in_date"] == "2026-11-10"
    assert result.json()["quote"]["check_out_date"] == "2026-11-12"
    assert result.json()["quote"]["provider_base_total"] == 240

    with Session(quote_app.engine) as db:
        reservation = db.get(Reservation, 1)
        assert reservation.check_in_date == date(2026, 11, 1)
        assert reservation.check_out_date == date(2026, 11, 3)
        assert reservation.total_price == 210


def test_absence_and_wrong_owner_are_indistinguishable_and_do_not_call_provider(quote_app):
    absent = quote_app.post(reservation_id=999)
    wrong_owner = quote_app.post(request_headers=headers(8))
    assert absent.status_code == wrong_owner.status_code == 404
    assert absent.json() == wrong_owner.json() == {"detail": "Reservation not found"}
    assert quote_app.calls == []


@pytest.mark.parametrize("request_headers", [{}, {"Authorization": "Bearer malformed"}, "partner", "missing-user"])
def test_authentication_and_partner_boundaries_precede_provider(quote_app, request_headers):
    if request_headers == "partner":
        request_headers = headers(7, "partner")
    elif request_headers == "missing-user":
        request_headers = headers(999)
    response = quote_app.post(request_headers=request_headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert quote_app.calls == []


@pytest.mark.parametrize("changes", [{"status": "deleted"}, {"session_version": 1}])
def test_inactive_or_revoked_customer_cannot_quote(quote_app, changes):
    change_record(quote_app, User, identity=7, **changes)
    assert quote_app.post().status_code == 401
    assert quote_app.calls == []


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_ineligible_reservations_never_revalidate(quote_app, status):
    change_record(quote_app, Reservation, status=status)
    assert quote_app.post().status_code == 409
    assert quote_app.calls == []


@pytest.mark.parametrize("changes", [
    {"check_in_date": "2026-01-01"}, {"check_out_date": "2026-11-10"},
    {"check_out_date": "2026-11-09"}, {"check_in_date": "2026-02-30"},
    {"check_in_date": "2026-11-10T00:00:00Z"}, {"adults": 0}, {"adults": 21},
    {"adults": True}, {"adults": "2"}, {"adults": 2.5}, {"children": -1},
    {"children": 21}, {"children": False}, {"children": "1"}, {"q": " \t "},
    {"q": "x" * 256}, {"currency": "EUR"}, {"gl": "gb"}, {"hl": "fr"},
    {"user_id": 8}, {"hotel_id": 99}, {"property_token": "client-selected"},
    {"hotel_token": "client-selected"}, {"original_booking_amount": 0.01},
    {"price_per_night": 0.01}, {"accepted_payment_amount": 0.01}, {"reward_points": 999},
])
def test_invalid_context_and_authority_fields_fail_before_provider(quote_app, changes):
    assert quote_app.post(review(**changes)).status_code == 422
    assert quote_app.calls == []


@pytest.mark.parametrize("missing", ["adults", "children", "q", "check_in_date", "check_out_date"])
def test_reconfirmation_has_no_invented_occupancy_defaults(quote_app, missing):
    body = review()
    del body[missing]
    assert quote_app.post(body).status_code == 422
    assert quote_app.calls == []


@pytest.mark.parametrize("token", ["", " ", "legacy:1", "partner:1", "PARTNER:1", " padded ", "bad\ntoken", "x" * 256])
def test_untrusted_property_tokens_fail_closed(quote_app, token):
    change_record(quote_app, Hotel, hotel_token=token)
    assert quote_app.post().status_code == 409
    assert quote_app.calls == []


@pytest.mark.parametrize("model,field", [(Reservation, "room_type_id"), (RoomType, "hotel_id")])
def test_missing_property_associations_fail_closed(quote_app, model, field):
    change_record(quote_app, model, **{field: 999})
    assert quote_app.post().status_code == 409
    assert quote_app.calls == []


@pytest.mark.parametrize("history", ["missing", "duplicate", "cancellation", "failed", "refunded", "cancellation-only", "inconsistent-amount"])
def test_ambiguous_or_inconsistent_payment_history_is_not_actionable(quote_app, history):
    with Session(quote_app.engine) as db:
        payment = db.get(Payment, 1)
        if history == "missing":
            db.delete(payment)
        elif history in ("duplicate", "cancellation"):
            db.add(Payment(reservation_id=1, amount=42,
                           payment_type="booking" if history == "duplicate" else "cancellation",
                           payment_status="pending"))
        elif history == "cancellation-only":
            payment.payment_type = "cancellation"
        elif history == "inconsistent-amount":
            payment.amount = 0.01
        else:
            payment.payment_status = history
        db.commit()
    assert quote_app.post().status_code == 409
    assert quote_app.calls == []


@pytest.mark.parametrize("model,field,value", [
    (Payment, "amount", -1), (Payment, "amount", 0), (Payment, "amount", 226.801),
    (Payment, "amount", 100000000), (Reservation, "total_price", -1),
    (RoomType, "price_per_night", 0),
])
def test_invalid_persisted_money_fails_before_provider(quote_app, model, field, value):
    change_record(quote_app, model, **{field: value})
    assert quote_app.post().status_code == 409
    assert quote_app.calls == []


@pytest.mark.parametrize("error,expected", [
    (SerpApiTimeoutError("private provider details"), 504),
    (SerpApiResponseError("private provider details"), 502),
    (SerpApiRequestError("private provider details"), 502),
    (SerpApiConfigError("private provider details"), 500),
])
def test_provider_failure_has_safe_response_and_no_writes(quote_app, monkeypatch, error, expected):
    def fail(_):
        raise error
    monkeypatch.setattr(serpapi_client, "search_google_hotels", fail)
    response = quote_app.post()
    assert response.status_code == expected
    assert "private" not in response.text


@pytest.mark.parametrize("payload", [None, {}, {"property_token": "different", "name": "Other", "prices": []},
                                      {"property_token": "synthetic-property-A", "name": "Hotel", "prices": []}])
def test_unavailable_or_mismatched_raw_provider_result_fails_closed(quote_app, monkeypatch, payload):
    monkeypatch.setattr(serpapi_client, "search_google_hotels", lambda _: payload)
    assert quote_app.post().status_code in (409, 502)


@pytest.mark.parametrize("field,value", [
    ("property_token", "another-property"), ("check_in_date", date(2026, 11, 11)),
    ("check_out_date", date(2026, 11, 13)), ("adults", 1), ("children", 0),
    ("adults", True), ("guest_capacity", True), ("guest_capacity", 2),
    ("guest_capacity", 9007199254740992), ("number_of_nights", 3),
    ("number_of_nights", 2.5), ("availability", "unavailable"), ("currency", "EUR"),
    ("rate_rule", "client-price"), ("hotel_name", " "), ("hotel_name", "x" * 256),
    ("source", ""), ("source", "x" * 20000), ("price_changed", True),
    ("current_price_per_night", 0), ("current_price_per_night", 0.001),
    ("provider_base_total", -1), ("provider_base_total", "240.00"),
    ("likehome_payment_amount", float("nan")), ("likehome_reservation_total", float("inf")),
    ("likehome_payment_amount", True), ("likehome_payment_amount", 100000000),
    ("provider_total_with_taxes_fees", 1), ("provider_total_with_taxes_fees", 100000000),
    ("current_price_per_night", 119), ("likehome_reservation_total", 251),
    ("likehome_payment_amount", 272.15),
])
def test_unverifiable_normalized_provider_quote_is_never_signed(quote_app, monkeypatch, field, value):
    original = hotel_service.revalidate_hotel
    def changed(info):
        quote = original(info).model_dump()
        quote[field] = value
        return quote
    monkeypatch.setattr(hotel_service, "revalidate_hotel", changed)
    response = quote_app.post()
    assert response.status_code == 502
    assert "quote_id" not in response.json()


def test_provider_rounding_uses_existing_base_total_rule_and_optional_all_in(quote_app, monkeypatch):
    def provider(params):
        return {"property_token": params["property_token"], "name": "Hotel",
                "prices": [{"source": "Provider", "num_guests": 3,
                            "rate_per_night": {"extracted_before_taxes_fees": 100},
                            "total_rate": {"extracted_before_taxes_fees": 201}}]}
    monkeypatch.setattr(serpapi_client, "search_google_hotels", provider)
    response = quote_app.post()
    assert response.status_code == 200
    quote = response.json()["quote"]
    assert quote["provider_total_with_taxes_fees"] is None
    assert quote["current_price_per_night"] == 100.5
    assert quote["likehome_reservation_total"] == 211.05
    assert quote["likehome_payment_amount"] == 227.93


def test_acknowledgement_is_scoped_private_from_logs_and_expires_at_ten_minutes(quote_app, monkeypatch, caplog):
    first, second = quote_app.post().json(), quote_app.post().json()
    assert first["quote_id"] != second["quote_id"]
    claims = verified(first)
    assert claims["purpose"] == "lh-review-v1"
    assert claims["expires_at"] - claims["issued_at"] == 600
    expiry = datetime.fromisoformat(first["expires_at"].replace("Z", "+00:00"))
    assert expiry == NOW + timedelta(minutes=10)
    assert claims["expires_at"] == int(expiry.timestamp())
    encoded_claims = json.dumps(claims)
    for excluded in ("guest_full_name", "guest_email", "owner@example.test", "synthetic-hash", AUTH_SECRET, REVIEW_SECRET):
        assert excluded not in encoded_claims
    assert first["quote_id"] not in caplog.text
    assert REVIEW_SECRET not in caplog.text
    monkeypatch.setattr(service, "_now", lambda: expiry - timedelta(microseconds=1))
    verified(first)
    monkeypatch.setattr(service, "_now", lambda: expiry)
    with pytest.raises(HTTPException) as error:
        verified(first)
    assert error.value.status_code == 409


@pytest.mark.parametrize("changes", [{"user_id": 8}, {"reservation_id": 2}])
def test_acknowledgement_cannot_cross_owner_or_reservation(quote_app, changes):
    with pytest.raises(HTTPException) as error:
        verified(quote_app.post().json(), **changes)
    assert error.value.status_code == 409


@pytest.mark.parametrize("mutation", ["leading-space", "trailing-space", "signature", "payload", "padding", "unicode", "oversize"])
def test_exact_acknowledgement_bytes_are_required(quote_app, mutation):
    body = quote_app.post().json()
    token = body["quote_id"]
    prefix, payload, signature = token.split(".")
    body["quote_id"] = {
        "leading-space": " " + token, "trailing-space": token + " ",
        "signature": prefix + "." + payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:],
        "payload": prefix + "." + payload[:-1] + ("A" if payload[-1] != "A" else "B") + "." + signature,
        "padding": prefix + "." + payload + "=." + signature,
        "unicode": token[:-1] + "🌍", "oversize": "x" * 16385,
    }[mutation]
    with pytest.raises(HTTPException) as error:
        verified(body)
    assert error.value.status_code == 409


def test_signed_state_context_and_quote_cannot_be_replaced(quote_app):
    body = quote_app.post().json()
    prefix, payload, signature = body["quote_id"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    for section, field, value in [("snapshot", "booking_payment_amount", "0.01"),
                                  ("snapshot", "check_in_date", "2026-11-09"),
                                  ("snapshot", "property_token", "different"),
                                  ("review", "adults", 1), ("review", "q", "Different destination"),
                                  ("quote", "likehome_payment_amount", 0.01)]:
        changed = json.loads(json.dumps(claims))
        changed[section][field] = value
        encoded = base64.urlsafe_b64encode(json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()).rstrip(b"=").decode()
        with pytest.raises(HTTPException):
            service.verify_review_acknowledgement(prefix + "." + encoded + "." + signature, user_id=7, reservation_id=1)


def test_quote_and_customer_partner_authentication_tokens_are_not_interchangeable(quote_app, monkeypatch):
    # Even with the SAME root secret, signing domains and wire formats differ.
    monkeypatch.setattr(service.Config, "JWT_SECRET_KEY", AUTH_SECRET)
    body = quote_app.post().json()
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=body["quote_id"])
    for role in ("user", "partner"):
        with pytest.raises(HTTPException) as error:
            auth.verify_access_token(bearer, subject_type=role)
        assert error.value.status_code == 401
        token = auth.create_access_token(7, subject_type=role)
        with pytest.raises(HTTPException):
            service.verify_review_acknowledgement(token, user_id=7, reservation_id=1)
    assert quote_app.post(request_headers={"Authorization": "Bearer " + body["quote_id"]}).status_code == 401
    # A JWT-shaped forgery signed with the authentication key is not a review.
    forged = jwt.encode({"sub": "7", "type": "user", "exp": NOW + timedelta(minutes=10)}, AUTH_SECRET, algorithm="HS256")
    with pytest.raises(HTTPException):
        service.verify_review_acknowledgement(forged, user_id=7, reservation_id=1)


@pytest.mark.parametrize("secret,algorithm", [(None, "HS256"), ("", "HS256"), ("short", "HS256"),
                                            (REVIEW_SECRET, "RS256"), ("-----BEGIN PUBLIC KEY-----" + "x" * 32, "HS256")])
def test_missing_or_unsafe_signing_configuration_fails_before_provider(quote_app, monkeypatch, secret, algorithm):
    monkeypatch.setattr(service.Config, "JWT_SECRET_KEY", secret)
    monkeypatch.setattr(service.Config, "JWT_ALGORITHM", algorithm)
    response = quote_app.post()
    assert response.status_code == 503
    assert quote_app.calls == []
    assert secret is None or not secret or secret not in response.text


def test_no_configuration_key_material_is_accepted_as_a_token(quote_app, monkeypatch):
    body = quote_app.post().json()
    monkeypatch.setattr(service.Config, "JWT_SECRET_KEY", "different-synthetic-review-secret-at-least-32")
    with pytest.raises(HTTPException):
        verified(body)


def test_database_failure_has_sanitized_response_and_no_provider_call(quote_app, monkeypatch):
    def fail(*args):
        raise SQLAlchemyError("private database credentials")
    monkeypatch.setattr(reservation_change_quote_dao, "get_owned_review_rows", fail)
    response = quote_app.post()
    assert response.status_code == 503
    assert "private" not in response.text
    assert quote_app.calls == []


def test_unexpected_provider_failure_is_sanitized(quote_app, monkeypatch):
    def fail(*args):
        raise RuntimeError("private provider credentials")
    monkeypatch.setattr(hotel_service, "revalidate_hotel", fail)
    response = quote_app.post()
    assert response.status_code == 502
    assert "private" not in response.text


def test_direct_service_revalidates_constructed_request_before_provider(quote_app):
    invalid = ReservationChangeReviewRequest.model_construct(**review(
        adults=True, check_in_date=date(2026, 11, 10), check_out_date=date(2026, 11, 12),
    ))
    with Session(quote_app.engine) as db, pytest.raises(HTTPException) as error:
        service.create_change_quote(db, 1, invalid, 7)
    assert error.value.status_code == 422
    assert quote_app.calls == []


def test_dao_read_cannot_autoflush_unrelated_pending_state(quote_app):
    before = database_state(quote_app.engine)
    with Session(quote_app.engine, autoflush=True) as db:
        db.add(Hotel(name="Unrelated uncommitted hotel", hotel_token="synthetic-uncommitted"))
        rows = reservation_change_quote_dao.get_owned_review_rows(db, 1, 7)
        assert len(rows) == 1 and len(db.new) == 1
        assert not db.dirty and not db.deleted
    assert database_state(quote_app.engine) == before
