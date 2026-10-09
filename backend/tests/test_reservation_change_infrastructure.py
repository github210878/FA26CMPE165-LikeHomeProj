"""Revision, money and receipt regressions; reuse isolated provider/HTTP fixtures."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Payment, Reservation, ReservationChangeEvent, RoomType
from app.repositories import booking_dao
from app.schemas import booking_schema, hotel_schema
from app.schemas.reservation_change_schema import ReservationChangeConfirmRequest, ReservationChangeReceiptRequest
from app.services import booking_service, reservation_change_idempotency as idempotency
from app.services.reservation_change_validation import validate_change_quote_acceptance
from app.utilities import reservation_change_quote as quotes
from app.utilities.reservation_change_serialization import canonical_money

from test_payment_integration import payment_app, headers as payment_headers
from test_reservation_change_quotes import NOW, fixed_review, info, load, quote_app, resigned, verify


def confirmation(review, **overrides):
    values = dict(
        check_in_date=review.quote.check_in_date, check_out_date=review.quote.check_out_date,
        quote_id=review.quote_id, accept_quote=True, price_per_night=review.quote.current_price_per_night,
        accepted_payment_amount=review.quote.likehome_payment_amount,
    )
    values.update(overrides)
    return ReservationChangeConfirmRequest(**values)


def fixture_event(review, records):
    """Simulated committed receipt in a disposable test DB, never a runtime write."""
    claims = quotes.decode_change_quote_claims(review.quote_id)
    request = confirmation(review)
    reservation, room, _, payments = records
    return ReservationChangeEvent(
        reservation_id=reservation.reservation_id, user_id=reservation.user_id,
        booking_payment_id=payments[0].payment_id, quote_jti=claims.jti,
        quote_sha256=idempotency.signed_quote_sha256(request.quote_id),
        request_sha256=idempotency.confirmation_request_sha256(request, reservation_id=1, user_id=7),
        original_state_sha256=bytes.fromhex(claims.state_fingerprint),
        revision_before=claims.reservation_revision, revision_after=claims.reservation_revision + 1,
        old_room_type_id=room.room_type_id, new_room_type_id=room.room_type_id,
        old_check_in_date=reservation.check_in_date, old_check_out_date=reservation.check_out_date,
        new_check_in_date=request.check_in_date, new_check_out_date=request.check_out_date,
        old_reservation_total=Decimal(str(reservation.total_price)),
        new_reservation_total=Decimal(canonical_money(review.quote.likehome_reservation_total)),
        old_payment_obligation=Decimal(str(payments[0].amount)),
        new_payment_obligation=Decimal(canonical_money(review.quote.likehome_payment_amount)),
        booking_payment_status_before=payments[0].payment_status, context_json=claims.context.model_dump(mode="json"),
        fresh_quote_json=review.quote.model_dump(mode="json"),
        response_json={"reservation_id": 1, "applied_revision": 1, "details": {"payment_obligation": "181.44"}},
        quote_issued_at=datetime.fromtimestamp(claims.iat, timezone.utc).replace(tzinfo=None),
        quote_expires_at=review.expires_at.replace(tzinfo=None),
    )


@pytest.fixture
def committed_receipt(quote_app):
    review, records = fixed_review(quote_app)
    with Session(quote_app[1]) as db:
        record = fixture_event(review, records)
        db.add(record)
        db.commit()
        db.refresh(record)
        db.expunge(record)
    return review, confirmation(review), record


def test_quote_binds_nonzero_revision_separately_from_format(quote_app):
    with Session(quote_app[1]) as db:
        db.get(Reservation, 1).revision = 7
        db.commit()
    review, records = fixed_review(quote_app)
    claims = quotes.decode_change_quote_claims(review.quote_id)
    assert claims.version == 2 and claims.reservation_revision == 7
    assert verify(review.quote_id, records).quote == review.quote
    records[0].revision = 8
    # Even a matching current fingerprint cannot rescue an obsolete revision.
    current_fingerprint = quotes.reservation_change_fingerprint(records[0], records[1], records[2], records[3][0])
    with pytest.raises(HTTPException) as error:
        verify(resigned(review.quote_id, {"state_fingerprint": current_fingerprint}), records)
    assert error.value.status_code == 409


@pytest.mark.parametrize("revision", [True, False, "0", -1, 1.5, None, 4294967296])
def test_malformed_revision_claims_are_rejected(quote_app, revision):
    review, records = fixed_review(quote_app)
    with pytest.raises(HTTPException) as error:
        verify(resigned(review.quote_id, {"reservation_revision": revision}), records)
    assert error.value.status_code == 409


@pytest.mark.parametrize("legacy", ["missing-revision", "version-one", "both"])
def test_old_quotes_require_new_review(quote_app, legacy):
    review, records = fixed_review(quote_app)
    token = resigned(review.quote_id, {"version": 1} if legacy != "missing-revision" else {},
                     remove="reservation_revision" if legacy != "version-one" else None)
    with pytest.raises(HTTPException) as error:
        verify(token, records)
    assert error.value.status_code == 409


def test_tampered_revision_fails_signature_and_lifetime_remains_ten_minutes(quote_app):
    review, records = fixed_review(quote_app)
    changed = resigned(review.quote_id, {"reservation_revision": 1})
    unsigned = ".".join([*changed.split(".")[:2], review.quote_id.split(".")[2]])
    with pytest.raises(HTTPException):
        verify(unsigned, records)
    assert review.expires_at == NOW + timedelta(minutes=10)
    assert verify(review.quote_id, records, now=review.expires_at - timedelta(microseconds=1))
    with pytest.raises(HTTPException):
        verify(review.quote_id, records, now=review.expires_at)


def test_signed_prices_are_canonical_and_public_prices_remain_numbers(quote_app):
    review, _ = fixed_review(quote_app)
    payload = jwt.decode(review.quote_id, options={"verify_signature": False})
    public = review.model_dump(mode="json")["quote"]
    for field in quotes.QUOTE_MONEY_FIELDS:
        value = public[field]
        if value is not None:
            assert isinstance(value, (int, float))
            assert payload["quote"][field] == canonical_money(value)
    assert public["likehome_payment_amount"] == 181.44


@pytest.mark.parametrize("value", [181.44, "181.440", "181.445"])
def test_signed_review_rejects_noncanonical_or_subcent_prices(quote_app, value):
    review, records = fixed_review(quote_app)
    payload = jwt.decode(review.quote_id, options={"verify_signature": False})
    payload["quote"]["likehome_payment_amount"] = value
    with pytest.raises(HTTPException) as error:
        verify(resigned(review.quote_id, {"quote": payload["quote"]}), records)
    assert error.value.status_code == 409


@pytest.mark.parametrize("value", [100, 100.0, Decimal("100.00"), Decimal("100.0000")])
def test_equivalent_money_produces_identical_fingerprints(quote_app, value):
    _, records = fixed_review(quote_app)
    reservation, room, hotel, payments = records
    original = quotes.reservation_change_fingerprint(reservation, room, hotel, payments[0])
    room.price_per_night = value
    reservation.total_price = Decimal("210.000")
    payments[0].amount = Decimal("226.8000")
    assert quotes.reservation_change_fingerprint(reservation, room, hotel, payments[0]) == original


@pytest.mark.parametrize("record_index,field", [(0, "total_price"), (1, "price_per_night"), (3, "amount")])
def test_distinct_cents_change_fingerprint(quote_app, record_index, field):
    _, records = fixed_review(quote_app)
    reservation, room, hotel, payments = records
    original = quotes.reservation_change_fingerprint(reservation, room, hotel, payments[0])
    target = records[record_index] if record_index != 3 else payments[0]
    setattr(target, field, Decimal(str(getattr(target, field))) + Decimal("0.01"))
    assert quotes.reservation_change_fingerprint(reservation, room, hotel, payments[0]) != original


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), Decimal("NaN"), Decimal("100000000")])
def test_canonical_money_fails_closed_for_invalid_values(value):
    with pytest.raises(ValueError):
        canonical_money(value)


def test_rounding_artifacts_do_not_change_acceptance_or_request_hash(quote_app):
    review, _ = fixed_review(quote_app)
    request = confirmation(review)
    artifact = confirmation(review, price_per_night=80 + 1e-12, accepted_payment_amount=181.44 + 1e-12)
    assert idempotency.confirmation_request_sha256(request, reservation_id=1, user_id=7) == idempotency.confirmation_request_sha256(
        artifact, reservation_id=1, user_id=7,
    )
    validate_change_quote_acceptance(artifact, review, review.quote, reservation_id=1, user_id=7, quote_owner_user_id=7, now=NOW)
    changed = confirmation(review, accepted_payment_amount=181.45)
    assert idempotency.confirmation_request_sha256(changed, reservation_id=1, user_id=7) != idempotency.confirmation_request_sha256(
        request, reservation_id=1, user_id=7,
    )
    with pytest.raises(HTTPException):
        validate_change_quote_acceptance(changed, review, review.quote, reservation_id=1, user_id=7, quote_owner_user_id=7, now=NOW)
    assert canonical_money(-0.0) == canonical_money(Decimal("0.00")) == "0.00"


def test_payment_and_cancellation_increment_existing_revision_exactly_once(payment_app):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(Reservation, 1).revision = 3
        db.commit()
    first = client.post("/bookings/pay/1", headers=payment_headers())
    repeated = client.post("/bookings/pay/1", headers=payment_headers())
    assert first.status_code == repeated.status_code == 200 and first.json() == repeated.json()
    assert first.json() == {"payment_id": 1, "reservation_id": 1, "amount": 226.8, "payment_type": "booking", "payment_status": "paid"}
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 4
    cancelled = client.post("/bookings/cancel-booking/1", headers=payment_headers())
    assert cancelled.status_code == 200 and cancelled.json()["cancellation_amount"] == 42
    assert cancelled.json()["booking_payment_status"] == "refunded"
    assert client.post("/bookings/cancel-booking/1", headers=payment_headers()).status_code == 409
    assert client.post("/bookings/pay/1", headers=payment_headers()).status_code == 409
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 5
        assert db.get(Reservation, 1).total_price == 210
        assert db.get(Reservation, 1).check_in_date.isoformat() == "2026-11-01"
        assert db.get(Payment, 1).amount == 226.8


@pytest.mark.parametrize("operation", ["pay", "cancel"])
def test_failed_commit_rolls_back_revision_and_financial_transition(payment_app, monkeypatch, operation):
    _, engine = payment_app
    with Session(engine) as db:
        db.get(Reservation, 1).revision = 4
        db.commit()

        def fail_commit():
            db.flush()
            assert db.get(Reservation, 1).revision == 5
            raise SQLAlchemyError("isolated failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(HTTPException) as error:
            if operation == "pay":
                booking_service.pay_booking_payment(db, 1, 7)
            else:
                booking_service.cancel_booking(db, 1, 7)
        assert error.value.status_code == 500
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 4
        assert db.get(Reservation, 1).status == "confirmed"
        assert db.get(Payment, 1).payment_status == "pending"
        assert len(list(db.scalars(select(Payment)))) == 1


@pytest.mark.parametrize("operation", ["pay", "cancel"])
@pytest.mark.parametrize("user_id", [8, 999])
def test_rejected_nonowner_operation_does_not_increment_revision(payment_app, operation, user_id):
    client, engine = payment_app
    path = "/bookings/pay/1" if operation == "pay" else "/bookings/cancel-booking/1"
    assert client.post(path, headers=payment_headers(user_id)).status_code == (404 if user_id == 8 else 401)
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 0


@pytest.mark.parametrize("status", ["failed", "refunded"])
def test_unsupported_payment_state_does_not_increment_revision(payment_app, status):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = status
        db.commit()
    assert client.post("/bookings/pay/1", headers=payment_headers()).status_code == 409
    assert client.post("/bookings/cancel-booking/1", headers=payment_headers()).status_code == 409
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 0


def test_payment_transition_invalidates_an_existing_review(quote_app):
    review, _ = fixed_review(quote_app)
    with Session(quote_app[1]) as db:
        booking_service.pay_booking_payment(db, 1, 7)
    records = load(quote_app[1])
    assert records[0].revision == 1
    with pytest.raises(HTTPException):
        verify(review.quote_id, records)


def test_missing_receipt_is_unconsumed_without_writes(quote_app):
    review, _ = fixed_review(quote_app)
    with Session(quote_app[1]) as db:
        assert idempotency.get_committed_change_receipt(db, confirmation(review), reservation_id=1, user_id=7, now=NOW) is None
        assert not db.new and not db.dirty
        assert list(db.scalars(select(ReservationChangeEvent))) == []


def test_receipt_is_a_detached_immutable_success_copy(committed_receipt, quote_app):
    _, request, record = committed_receipt
    original = json.loads(json.dumps(record.response_json))
    receipt = idempotency.verify_committed_change_receipt(record, request, reservation_id=1, user_id=7, now=NOW)
    assert receipt == original and receipt is not record.response_json
    receipt["details"]["payment_obligation"] = "corrupted caller copy"
    assert record.response_json == original
    provider_calls_before = list(quote_app[2])
    with Session(quote_app[1]) as db:
        assert idempotency.get_committed_change_receipt(db, request, reservation_id=1, user_id=7, now=NOW) == original
    assert quote_app[2] == provider_calls_before


@pytest.mark.parametrize("field,value", [
    ("quote_sha256", b"x" * 32), ("request_sha256", b"x" * 32), ("quote_sha256", b"short"),
    ("user_id", 8), ("reservation_id", 2), ("quote_jti", str(uuid4())),
    ("revision_before", 7), ("revision_after", 9), ("response_json", None), ("response_json", []),
    ("response_json", {}), ("response_json", {"amount": float("nan")}),
])
def test_conflicting_or_malformed_persisted_receipt_is_rejected(committed_receipt, field, value):
    _, request, record = committed_receipt
    setattr(record, field, value)
    with pytest.raises(HTTPException) as error:
        idempotency.verify_committed_change_receipt(record, request, reservation_id=1, user_id=7, now=NOW)
    assert error.value.status_code == 409


@pytest.mark.parametrize("overrides", [{"price_per_night": 80.01}, {"accepted_payment_amount": 181.45}, {"check_out_date": "2026-11-07"}])
def test_same_quote_with_different_confirmation_is_rejected(committed_receipt, overrides):
    review, _, record = committed_receipt
    with pytest.raises(HTTPException) as error:
        idempotency.verify_committed_change_receipt(record, confirmation(review, **overrides), reservation_id=1, user_id=7, now=NOW)
    assert error.value.status_code == 409


@pytest.mark.parametrize("user_id,reservation_id", [(8, 1), (7, 2), (True, 1), (7, True)])
def test_receipt_lookup_enforces_signed_owner_and_path_identity(committed_receipt, quote_app, user_id, reservation_id):
    _, request, _ = committed_receipt
    with Session(quote_app[1]) as db, pytest.raises(HTTPException) as error:
        idempotency.get_committed_change_receipt(db, request, reservation_id=reservation_id, user_id=user_id, now=NOW)
    assert error.value.status_code == 409


def test_token_hash_rejects_even_a_validly_resigned_different_token(committed_receipt):
    review, _, record = committed_receipt
    request = confirmation(review, quote_id=resigned(review.quote_id, {"iat": int(NOW.timestamp()) + 1, "exp": int(NOW.timestamp()) + 601}))
    with pytest.raises(HTTPException) as error:
        idempotency.verify_committed_change_receipt(record, request, reservation_id=1, user_id=7, now=NOW + timedelta(seconds=2))
    assert error.value.status_code == 409


def test_exact_expired_receipt_survives_later_calendar_and_reservation_state(committed_receipt, quote_app, monkeypatch):
    review, request, record = committed_receipt

    class LaterDate(booking_schema.date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 1)

    monkeypatch.setattr(booking_schema, "date", LaterDate)
    monkeypatch.setattr(hotel_schema, "date", LaterDate)
    with pytest.raises(ValidationError):
        ReservationChangeConfirmRequest(**request.model_dump())
    historical = ReservationChangeReceiptRequest(**request.model_dump())
    later = NOW + timedelta(days=100)
    with Session(quote_app[1]) as db:
        db.get(Reservation, 1).revision = 9
        db.get(Reservation, 1).status = "cancelled"
        db.commit()
        assert idempotency.get_committed_change_receipt(db, historical, reservation_id=1, user_id=7, now=later) == record.response_json
    assert quotes.decode_change_quote_claims(review.quote_id).reservation_revision == 0


def test_lookup_cannot_autoflush_or_consume_staged_events(committed_receipt, quote_app):
    review, request, record = committed_receipt
    statements = []

    def observed(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(quote_app[1], "before_cursor_execute", observed)
    try:
        with Session(quote_app[1]) as db:
            staged = fixture_event(review, load(quote_app[1]))
            staged.quote_jti = str(uuid4())
            staged.revision_after = 2
            db.add(staged)
            assert idempotency.get_committed_change_receipt(db, request, reservation_id=1, user_id=7, now=NOW) == record.response_json
            assert staged in db.new and not db.dirty
            db.rollback()
        assert not {"INSERT", "UPDATE", "DELETE"}.intersection(statements)
    finally:
        event.remove(quote_app[1], "before_cursor_execute", observed)


def test_dao_lookup_does_not_expose_another_owners_receipt(committed_receipt, quote_app):
    _, _, record = committed_receipt
    with Session(quote_app[1]) as db:
        assert booking_dao.get_owned_change_event_by_quote_jti(db, record.quote_jti, 1, 8) is None
        assert booking_dao.get_owned_change_event_by_quote_jti(db, record.quote_jti, 2, 7) is None
