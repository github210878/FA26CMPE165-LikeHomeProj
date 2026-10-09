"""Atomic confirmation with disposable SQLite databases and mocked providers.

Threaded tests simulate InnoDB's User-row wait using a Python mutex around real
SQLite Sessions. They verify orchestration/atomic persistence, not InnoDB locks.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier, Lock
import sqlite3

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.config.database import Base
from app.models import Hotel, Payment, Reservation, ReservationChangeAdjustment, ReservationChangeEvent, RoomType, User
from app.repositories import booking_dao
from app.schemas.reservation_change_schema import ReservationChangeConfirmRequest, ReservationChangeReceiptRequest
from app.services import booking_service, hotel_service, reservation_change_service as service, reservation_change_validation
from app.utilities import reservation_change_quote as signing
from app.utilities.serpapi_client import SerpApiTimeoutError

from test_reservation_change_quotes import NOW, REQUEST, info, quote_app, resigned


TABLES = (User, Hotel, RoomType, Reservation, Payment, ReservationChangeEvent, ReservationChangeAdjustment)


def review(engine, **changes):
    with Session(engine) as db:
        records = booking_dao.get_owned_reservation_for_change(db, 1, 7)
        context = info(records, **changes)
        trusted = hotel_service.revalidate_hotel(context)
        reservation, room, hotel, payments = records
        return signing.issue_reservation_change_quote(
            reservation=reservation, room_type=room, hotel=hotel, payment=payments[0],
            user_id=7, context=context, quote=trusted, now=NOW,
        )


def confirmation(reviewed, **changes):
    return ReservationChangeConfirmRequest(
        **dict({"check_in_date": reviewed.quote.check_in_date,
                "check_out_date": reviewed.quote.check_out_date, "quote_id": reviewed.quote_id,
                "accept_quote": True, "price_per_night": reviewed.quote.current_price_per_night,
                "accepted_payment_amount": reviewed.quote.likehome_payment_amount}, **changes),
    )


def confirm(engine, request, *, reservation_id=1, user_id=7, now=NOW):
    with Session(engine) as db:
        return service.confirm_reservation_change(db, request, reservation_id, user_id, now=now)


def snapshot(engine):
    with Session(engine) as db:
        return {model.__tablename__: [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in db.scalars(select(model).order_by(*model.__table__.primary_key.columns)).all()
        ] for model in TABLES}


def assert_conflict(engine, request, expected=409, **kwargs):
    before = snapshot(engine)
    with pytest.raises(HTTPException) as error:
        confirm(engine, request, **kwargs)
    assert error.value.status_code == expected
    assert snapshot(engine) == before


@pytest.mark.parametrize("status", ["pending", "paid"])
@pytest.mark.parametrize("old_amount,expected_difference", [(100, "81.44"), (200, "-18.56"), (181.44, "0.00")])
def test_atomic_financial_change(quote_app, status, old_amount, expected_difference):
    _, engine, calls, _ = quote_app
    with Session(engine) as db:
        payment = db.get(Payment, 1)
        payment.payment_status = status
        payment.amount = old_amount
        reservation = db.get(Reservation, 1)
        reservation.guest_full_name = "Original Guest"
        reservation.guest_email = "guest@example.test"
        # Another user's reservation shares the original rate record.
        db.add(Reservation(reservation_id=2, user_id=8, room_type_id=1, check_in_date=date(2026, 11, 1),
                           check_out_date=date(2026, 11, 3), total_price=210, status="confirmed"))
        db.commit()
    reviewed = review(engine)
    before = snapshot(engine)
    receipt = confirm(engine, confirmation(reviewed))
    assert len(calls) == 2
    assert receipt["revision"] == 1 and receipt["payment_difference"] == expected_difference
    assert receipt["reservation_total"] == "168.00" and receipt["payment_obligation"] == "181.44"
    with Session(engine) as db:
        reservation = db.get(Reservation, 1)
        payment = db.get(Payment, 1)
        assert reservation.check_in_date == date(2026, 11, 4)
        assert reservation.check_out_date == date(2026, 11, 6)
        assert reservation.total_price == 168 and reservation.revision == 1
        assert reservation.user_id == 7 and reservation.status == "confirmed"
        assert reservation.guest_full_name == "Original Guest" and reservation.guest_email == "guest@example.test"
        new_room = db.get(RoomType, reservation.room_type_id)
        assert new_room.price_per_night == 80 and new_room.hotel_id == 1
        assert db.get(RoomType, 1).price_per_night == 100
        assert db.get(Reservation, 2).room_type_id == 1 and db.get(Reservation, 2).total_price == 210
        assert payment.amount == (181.44 if status == "pending" else old_amount)
        assert payment.payment_status == status
        assert len(db.scalars(select(Payment)).all()) == 1
        events = db.scalars(select(ReservationChangeEvent)).all()
        assert len(events) == 1
        change = events[0]
        assert change.response_json == receipt
        assert change.revision_before == 0 and change.revision_after == 1
        assert change.old_payment_obligation == Decimal(str(old_amount))
        assert change.new_payment_obligation == Decimal("181.44")
        assert change.old_reservation_total == Decimal("210.00") and change.new_reservation_total == Decimal("168.00")
        assert change.old_room_type_id == 1 and change.new_room_type_id == reservation.room_type_id
        assert change.old_check_in_date == date(2026, 11, 1) and change.old_check_out_date == date(2026, 11, 3)
        assert change.user_id == 7 and change.reservation_id == 1 and change.booking_payment_id == 1
        assert change.booking_payment_status_before == status and change.currency == "USD"
        claims = signing.decode_change_quote_claims(reviewed.quote_id)
        assert change.quote_jti == claims.jti and change.original_state_sha256 == bytes.fromhex(claims.state_fingerprint)
        assert len(change.quote_sha256) == len(change.request_sha256) == 32
        assert change.quote_issued_at == NOW.replace(tzinfo=None)
        assert change.quote_expires_at == (NOW + timedelta(minutes=10)).replace(tzinfo=None)
        assert change.context_json == claims.context.model_dump(mode="json")
        assert change.fresh_quote_json["provider_base_total"] == "160.00"
        assert change.fresh_quote_json["likehome_payment_amount"] == "181.44"
        assert reviewed.quote_id not in str(change.context_json) + str(change.fresh_quote_json) + str(change.response_json)
        adjustments = db.scalars(select(ReservationChangeAdjustment)).all()
        if status == "paid" and Decimal(expected_difference):
            assert len(adjustments) == 1
            adjustment = adjustments[0]
            assert adjustment.change_id == change.change_id
            assert adjustment.amount == abs(Decimal(expected_difference))
            assert adjustment.kind == ("charge" if old_amount < 181.44 else "credit")
            assert adjustment.status == ("pending" if old_amount < 181.44 else "recorded")
            assert adjustment.entry_role == "price_change" and adjustment.reconciles_adjustment_id is None
            assert adjustment.settled_at is None
            assert receipt["adjustment"]["adjustment_id"] == adjustment.adjustment_id
        else:
            assert adjustments == [] and receipt["adjustment"] is None
    after = snapshot(engine)
    assert after["users"] == before["users"] and after["hotels"] == before["hotels"]


@pytest.mark.parametrize("user_id,reservation_id,status", [(8, 1, 404), (7, 999, 404), (999, 1, 401)])
def test_ownership_missing_user_and_missing_reservation(quote_app, user_id, reservation_id, status):
    _, engine, calls, _ = quote_app
    request = confirmation(review(engine))
    assert_conflict(engine, request, expected=status, user_id=user_id, reservation_id=reservation_id)
    assert len(calls) == 1


@pytest.mark.parametrize("case", ["cancelled", "completed", "started", "past", "failed", "refunded", "duplicate", "missing_payment", "cancellation_payment", "inactive"])
def test_ineligible_state_is_rejected_without_provider(quote_app, case):
    _, engine, calls, _ = quote_app
    request = confirmation(review(engine))
    with Session(engine) as db:
        reservation, payment = db.get(Reservation, 1), db.get(Payment, 1)
        if case in ("cancelled", "completed"):
            reservation.status = case
        elif case in ("started", "past"):
            reservation.check_in_date = date(2026, 9, 29 if case == "started" else 28)
        elif case in ("failed", "refunded"):
            payment.payment_status = case
        elif case == "duplicate":
            db.add(Payment(reservation_id=1, amount=10, payment_type="booking", payment_status="pending"))
        elif case == "missing_payment":
            db.delete(payment)
        elif case == "cancellation_payment":
            db.add(Payment(reservation_id=1, amount=10, payment_type="cancellation", payment_status="pending"))
        else:
            db.get(User, 7).status = "deleted"
        db.commit()
    assert_conflict(engine, request, expected=401 if case == "inactive" else 409)
    assert len(calls) == 1


@pytest.mark.parametrize("case", ["expired", "purpose", "tampered", "revision", "old_format", "missing_revision", "hotel", "context", "dates", "nightly_ack", "payment_ack", "fingerprint", "property"])
def test_quote_security_guards(quote_app, case):
    _, engine, calls, _ = quote_app
    reviewed = review(engine)
    kwargs = {}
    now = NOW
    if case == "expired":
        now += timedelta(minutes=10)
    elif case == "purpose":
        kwargs["quote_id"] = resigned(reviewed.quote_id, {"type": "access"})
    elif case == "tampered":
        pieces = reviewed.quote_id.split(".")
        pieces[2] = ("A" if pieces[2][0] != "A" else "B") + pieces[2][1:]
        kwargs["quote_id"] = ".".join(pieces)
    elif case == "revision":
        kwargs["quote_id"] = resigned(reviewed.quote_id, {"reservation_revision": 1})
    elif case == "old_format":
        kwargs["quote_id"] = resigned(reviewed.quote_id, {"version": 1})
    elif case == "missing_revision":
        kwargs["quote_id"] = resigned(reviewed.quote_id, remove="reservation_revision")
    elif case == "hotel":
        kwargs["quote_id"] = resigned(reviewed.quote_id, {"hotel_id": 2})
    elif case == "context":
        claims = signing.decode_change_quote_claims(reviewed.quote_id)
        kwargs["quote_id"] = resigned(reviewed.quote_id, {"context": {**claims.context.model_dump(mode="json"), "adults": 2}})
    elif case == "dates":
        kwargs["check_out_date"] = "2026-11-07"
    elif case in ("nightly_ack", "payment_ack"):
        kwargs["price_per_night" if case == "nightly_ack" else "accepted_payment_amount"] = 1
    elif case == "fingerprint":
        with Session(engine) as db:
            db.get(Reservation, 1).guest_email = "changed@example.test"
            db.commit()
    else:
        with Session(engine) as db:
            db.get(Hotel, 1).hotel_token = "replacement-property"
            db.commit()
    assert_conflict(engine, confirmation(reviewed, **kwargs), now=now)
    assert len(calls) == 1


@pytest.mark.parametrize("case,expected", [("changed_rate", 409), ("unavailable", 409), ("wrong_property", 409), ("timeout", 504)])
def test_fresh_provider_failure_rolls_back_without_fallback(quote_app, monkeypatch, case, expected):
    _, engine, calls, provider_state = quote_app
    reviewed = review(engine)
    if case == "changed_rate":
        original = hotel_service.revalidate_hotel
        monkeypatch.setattr(hotel_service, "revalidate_hotel", lambda context: original(context).model_copy(update={"likehome_payment_amount": 181.45}))
    elif case == "timeout":
        provider_state["error"] = SerpApiTimeoutError("simulated timeout")
    else:
        provider_state[case] = True
    assert_conflict(engine, confirmation(reviewed), expected=expected)
    assert len(calls) == 2


@pytest.mark.parametrize("room_id,status,dates,blocked", [
    (1, "confirmed", (4, 6), True), (2, "confirmed", (4, 6), True),
    (2, "completed", (4, 6), True), (2, "cancelled", (4, 6), False),
    (1, "confirmed", (2, 4), False), (2, "confirmed", (6, 8), False),
])
def test_overlap_rules_rechecked_inside_transaction(quote_app, monkeypatch, room_id, status, dates, blocked):
    _, engine, calls, _ = quote_app
    request = confirmation(review(engine))
    original = hotel_service.revalidate_hotel

    def provider(context):
        fresh = original(context)
        # A competing booking commits while the provider is being called.
        with Session(engine) as db:
            db.add(Reservation(reservation_id=2, user_id=7, room_type_id=room_id, total_price=100, status=status,
                               check_in_date=date(2026, 11, dates[0]), check_out_date=date(2026, 11, dates[1])))
            db.commit()
        return fresh

    monkeypatch.setattr(hotel_service, "revalidate_hotel", provider)
    if blocked:
        with pytest.raises(HTTPException) as error:
            confirm(engine, request)
        assert error.value.status_code == 409
        with Session(engine) as db:
            assert db.get(Reservation, 1).revision == 0
            assert db.get(Reservation, 1).check_in_date == date(2026, 11, 1)
            assert len(db.scalars(select(ReservationChangeEvent)).all()) == 0
            assert db.get(Reservation, 2) is not None
    else:
        assert confirm(engine, request)["revision"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize("case", ["payment", "cancellation", "revision", "fingerprint", "property", "user", "ownership", "missing", "new_payment"])
def test_state_changes_during_provider_are_rechecked(quote_app, monkeypatch, case):
    _, engine, _, _ = quote_app
    request = confirmation(review(engine))
    original = hotel_service.revalidate_hotel
    competing_state = None

    def provider(context):
        nonlocal competing_state
        fresh = original(context)
        with Session(engine) as db:
            reservation = db.get(Reservation, 1)
            if case == "payment":
                booking_service.pay_booking_payment(db, 1, 7)
            elif case == "cancellation":
                booking_service.cancel_booking(db, 1, 7)
            elif case == "revision":
                reservation.revision += 1
            elif case == "fingerprint":
                reservation.guest_full_name = "A different snapshot"
            elif case == "property":
                db.get(Hotel, 1).hotel_token = "replacement-property"
            elif case == "user":
                db.get(User, 7).status = "deleted"
            elif case == "ownership":
                reservation.user_id = 8
            elif case == "missing":
                db.delete(reservation)
            else:
                db.add(Payment(reservation_id=1, amount=20, payment_type="booking", payment_status="pending"))
            db.commit()
        competing_state = snapshot(engine)
        return fresh

    monkeypatch.setattr(hotel_service, "revalidate_hotel", provider)
    with pytest.raises(HTTPException) as error:
        confirm(engine, request)
    assert error.value.status_code == (401 if case == "user" else 404 if case in ("ownership", "missing") else 409)
    assert snapshot(engine) == competing_state


@pytest.mark.parametrize("status", ["pending", "paid"])
def test_repeat_confirmation_and_expired_historical_retry(quote_app, status):
    _, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = status
        db.commit()
    request = confirmation(review(engine))
    receipt = confirm(engine, request)
    before = snapshot(engine)
    assert confirm(engine, request) == receipt
    historical = ReservationChangeReceiptRequest(**request.model_dump())
    assert confirm(engine, historical, now=NOW + timedelta(days=100)) == receipt
    assert snapshot(engine) == before and len(calls) == 2
    receipt["reservation_total"] = "corrupted by caller"
    assert confirm(engine, request)["reservation_total"] == "168.00"


@pytest.mark.parametrize("change", [{"price_per_night": 80.01}, {"accepted_payment_amount": 181.45}, {"check_out_date": "2026-11-07"}])
def test_committed_quote_rejects_different_request(quote_app, change):
    _, engine, calls, _ = quote_app
    reviewed = review(engine)
    confirm(engine, confirmation(reviewed))
    assert_conflict(engine, confirmation(reviewed, **change))
    assert len(calls) == 2


@pytest.mark.parametrize("payment_status", ["pending", "paid"])
def test_second_change_uses_latest_committed_obligation(quote_app, payment_status):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = payment_status
        db.commit()
    first = confirm(engine, confirmation(review(engine)))  # 226.80 -> 181.44
    second = review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")
    receipt = confirm(engine, confirmation(second))  # 181.44 -> 272.16
    assert first["payment_difference"] == "-45.36"
    assert receipt["previous_payment_obligation"] == "181.44" and receipt["payment_difference"] == "90.72"
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 2
        assert db.get(Payment, 1).amount == (272.16 if payment_status == "pending" else 226.8)
        changes = db.scalars(select(ReservationChangeEvent).order_by(ReservationChangeEvent.change_id)).all()
        assert len(changes) == 2 and changes[0].response_json == first
        assert changes[1].old_payment_obligation == Decimal("181.44")
        adjustments = db.scalars(select(ReservationChangeAdjustment).order_by(ReservationChangeAdjustment.adjustment_id)).all()
        if payment_status == "paid":
            assert [(row.kind, row.status, row.amount) for row in adjustments] == [
                ("credit", "recorded", Decimal("45.36")), ("charge", "pending", Decimal("90.72")),
            ]
        else:
            assert adjustments == []


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_unsettled_charge_blocks_another_change_without_offsetting_credit(quote_app, status):
    _, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.commit()
    confirm(engine, confirmation(review(engine)))  # recorded credit
    confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")))
    with Session(engine) as db:
        charge = db.scalars(select(ReservationChangeAdjustment).where(ReservationChangeAdjustment.kind == "charge")).one()
        charge.status = status
        db.commit()
    request = confirmation(review(engine, check_in_date="2026-11-15", check_out_date="2026-11-17"))
    count = len(calls)
    assert_conflict(engine, request)
    assert len(calls) == count


@pytest.mark.parametrize("stage", ["room", "event", "adjustment", "commit", "deadlock"])
def test_failure_rolls_back_every_write(quote_app, monkeypatch, stage):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.get(Payment, 1).amount = 100
        db.commit()
    request = confirmation(review(engine))
    before = snapshot(engine)
    original_stage = booking_dao.stage_booking_record

    def stage_record(db, record):
        result = original_stage(db, record)
        target = {"room": RoomType, "event": ReservationChangeEvent, "adjustment": ReservationChangeAdjustment}.get(stage)
        if target and isinstance(record, target):
            assert db.in_transaction()
            raise RuntimeError("injected post-flush failure")
        return result

    monkeypatch.setattr(booking_dao, "stage_booking_record", stage_record)
    with Session(engine) as db:
        if stage == "commit":
            monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failure")))
        elif stage == "deadlock":
            monkeypatch.setattr(booking_dao, "lock_reservation_for_change", lambda *_: (_ for _ in ()).throw(OperationalError("lock", {}, Exception("deadlock"))))
        with pytest.raises(HTTPException) as error:
            service.confirm_reservation_change(db, request, 1, 7, now=NOW)
        assert error.value.status_code == 500 and not db.in_transaction()
    assert snapshot(engine) == before


def test_lock_order_one_commit_fresh_snapshot_and_no_provider_lock(quote_app, monkeypatch):
    _, engine, calls, _ = quote_app
    request = confirmation(review(engine))
    order = []
    for name in ("lock_user_for_booking", "lock_reservation_for_change", "lock_payments_for_change", "get_adjustments_for_change"):
        original = getattr(booking_dao, name)

        def traced(*args, _name=name, _original=original, **kwargs):
            if _name != "get_adjustments_for_change" or kwargs.get("lock"):
                order.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(booking_dao, name, traced)
    provider = hotel_service.revalidate_hotel
    monkeypatch.setattr(hotel_service, "revalidate_hotel", lambda context: (order.append("provider"), provider(context))[1])
    with Session(engine) as db:
        stale = db.get(Reservation, 1)
        payment = db.get(Payment, 1)
        assert stale.revision == 0 and payment.amount == 226.8
        commits = []
        rollbacks = []
        event.listen(db, "after_commit", lambda _: commits.append(True))
        event.listen(db, "after_rollback", lambda _: rollbacks.append(True))
        service.confirm_reservation_change(db, request, 1, 7, now=NOW)
        assert commits == [True] and rollbacks == [True]
    assert order == ["provider", "lock_user_for_booking", "lock_reservation_for_change", "lock_payments_for_change", "get_adjustments_for_change"]
    assert len(calls) == 2


def test_quote_service_still_available_and_confirmation_is_unregistered(quote_app):
    client, _, _, _ = quote_app
    from test_reservation_change_quotes import headers

    assert client.post("/bookings/1/change-quote", headers=headers(), json=REQUEST).status_code == 200
    assert client.post("/bookings/1/change-confirm", headers=headers(), json={}).status_code == 404
    assert not any("confirm_reservation_change" == getattr(route, "name", None) for route in client.app.routes)


@pytest.mark.parametrize("status", ["pending", "paid"])
def test_existing_pay_and_cancellation_after_change_without_adjustment(quote_app, status):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = status
        db.get(Payment, 1).amount = 181.44  # equal-price change: no ledger entry
        db.commit()
    confirm(engine, confirmation(review(engine)))
    with Session(engine) as db:
        assert booking_service.pay_booking_payment(db, 1, 7).amount == 181.44
        cancelled = booking_service.cancel_booking(db, 1, 7)
        assert cancelled.cancellation_amount == pytest.approx(33.60)
        assert cancelled.booking_payment_status == "refunded"
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == (3 if status == "pending" else 2)
        assert len(db.scalars(select(ReservationChangeEvent)).all()) == 1


@pytest.fixture
def threaded_database(quote_app, tmp_path, monkeypatch):
    """Real SQLite persistence, with an explicitly simulated User row lock."""
    source = quote_app[1]
    engine = create_engine(f"sqlite:///{tmp_path / 'changes.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(source) as old, Session(engine) as db:
        for model in TABLES:
            for row in old.scalars(select(model)).all():
                db.add(model(**{column.name: getattr(row, column.name) for column in model.__table__.columns}))
            db.flush()
        db.commit()
    mutex = Lock()
    original_lock = booking_dao.lock_user_for_booking

    def lock_user(db, user_id):
        assert not db.in_transaction()  # prior read transaction was ended
        mutex.acquire()
        db.info["simulated_user_lock"] = True
        return original_lock(db, user_id)

    def release(db, *_):
        if db.info.pop("simulated_user_lock", False):
            mutex.release()

    monkeypatch.setattr(booking_dao, "lock_user_for_booking", lock_user)
    event.listen(Session, "after_commit", release)
    event.listen(Session, "after_rollback", release)
    try:
        yield engine
    finally:
        event.remove(Session, "after_commit", release)
        event.remove(Session, "after_rollback", release)
        engine.dispose()


@pytest.mark.parametrize("same_quote", [True, False])
@pytest.mark.parametrize("payment_status", ["pending", "paid"])
def test_competing_confirmations_same_quote_or_same_revision(threaded_database, monkeypatch, same_quote, payment_status):
    engine = threaded_database
    with Session(engine) as db:
        db.get(Payment, 1).amount = 100
        db.get(Payment, 1).payment_status = payment_status
        db.commit()
    reviewed = review(engine)
    other = reviewed if same_quote else review(engine, check_in_date="2026-11-08", check_out_date="2026-11-10")
    barrier = Barrier(2)
    original_provider = hotel_service.revalidate_hotel

    def provider(context):
        result = original_provider(context)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(hotel_service, "revalidate_hotel", provider)

    def attempt(request):
        try:
            return confirm(engine, request)
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [confirmation(reviewed), confirmation(other)]))
    if same_quote:
        assert results[0] == results[1] and isinstance(results[0], dict)
    else:
        assert sum(isinstance(value, dict) for value in results) == 1 and 409 in results
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 1
        assert len(db.scalars(select(ReservationChangeEvent)).all()) == 1
        adjustments = db.scalars(select(ReservationChangeAdjustment)).all()
        assert len(adjustments) == (1 if payment_status == "paid" else 0)
        assert len(db.scalars(select(Payment)).all()) == 1
        assert db.get(Payment, 1).amount == (100 if payment_status == "paid" else 181.44)


def test_competing_changes_on_different_stays_cannot_create_overlap(threaded_database, monkeypatch):
    engine = threaded_database
    with Session(engine) as db:
        db.add(Reservation(reservation_id=2, user_id=7, room_type_id=2, total_price=210, status="confirmed",
                           check_in_date=date(2026, 12, 1), check_out_date=date(2026, 12, 3)))
        db.add(Payment(payment_id=2, reservation_id=2, amount=226.8, payment_type="booking", payment_status="pending"))
        db.commit()
    first = review(engine)
    with Session(engine) as db:
        records = booking_dao.get_owned_reservation_for_change(db, 2, 7)
        context = info(records)
        trusted = hotel_service.revalidate_hotel(context)
        second = signing.issue_reservation_change_quote(reservation=records[0], room_type=records[1], hotel=records[2],
                    payment=records[3][0], user_id=7, context=context, quote=trusted, now=NOW)
    barrier = Barrier(2)
    original = hotel_service.revalidate_hotel
    monkeypatch.setattr(hotel_service, "revalidate_hotel", lambda context: (original(context), barrier.wait(timeout=10))[0])

    def attempt(values):
        request, reservation_id = values
        try:
            return confirm(engine, request, reservation_id=reservation_id)
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [(confirmation(first), 1), (confirmation(second), 2)]))
    assert sum(isinstance(value, dict) for value in results) == 1 and 409 in results
    with Session(engine) as db:
        assert sum(row.revision for row in db.scalars(select(Reservation))) == 1
        assert len(db.scalars(select(ReservationChangeEvent)).all()) == 1


def sqlite_unique_error(message):
    error = sqlite3.IntegrityError(message)
    error.sqlite_errorname = "SQLITE_CONSTRAINT_UNIQUE"
    return IntegrityError("INSERT", {}, error)


@pytest.mark.parametrize("message,expected", [
    ("UNIQUE constraint failed: reservation_change_events.quote_jti", True),
    ("UNIQUE constraint failed: reservation_change_events.reservation_id, reservation_change_events.revision_after", True),
    ("UNIQUE constraint failed: hotels.hotel_token", False),
    ("UNIQUE constraint failed: reservation_change_adjustments.change_id, reservation_change_adjustments.entry_role", False),
])
def test_uniqueness_classifier_does_not_swallow_unrelated_errors(message, expected):
    assert service._change_uniqueness_conflict(sqlite_unique_error(message)) is expected


@pytest.mark.parametrize("code,message,expected", [
    (1062, "Duplicate entry 'jti' for key 'uq_change_quote_jti'", True),
    (1062, "Duplicate entry '1-1' for key 'reservation_change_events.uq_change_reservation_revision'", True),
    (1062, "Duplicate entry 'uq_change_quote_jti' for key 'hotels.hotel_token'", False),
    (1452, "Cannot add or update a child row: uq_change_quote_jti", False),
])
def test_mysql_uniqueness_error_classification_without_mysql_connection(code, message, expected):
    assert service._change_uniqueness_conflict(IntegrityError("INSERT", {}, Exception(code, message))) is expected


@pytest.mark.parametrize("kind,expected", [("revision", 409), ("quote", 409), ("unrelated", 500)])
def test_integrity_failure_rolls_back_and_requires_a_real_committed_receipt(quote_app, monkeypatch, kind, expected):
    _, engine, _, _ = quote_app
    request = confirmation(review(engine))
    original = booking_dao.stage_booking_record

    def fail(db, record):
        result = original(db, record)
        if isinstance(record, ReservationChangeEvent):
            field = {"revision": "reservation_change_events.reservation_id, reservation_change_events.revision_after",
                     "quote": "reservation_change_events.quote_jti", "unrelated": "hotels.hotel_token"}[kind]
            raise sqlite_unique_error("UNIQUE constraint failed: " + field)
        return result

    monkeypatch.setattr(booking_dao, "stage_booking_record", fail)
    assert_conflict(engine, request, expected=expected)


@pytest.mark.parametrize("same_jti", [True, False])
def test_real_database_event_uniqueness_rolls_back_entire_candidate(quote_app, monkeypatch, same_jti):
    """Constraint errors originate from SQLite, not a mocked exception."""
    from test_reservation_change_infrastructure import fixture_event

    _, engine, _, _ = quote_app
    reviewed = review(engine)
    request = confirmation(reviewed)
    with Session(engine) as db:
        records = booking_dao.get_owned_reservation_for_change(db, 1, 7)
        duplicate = fixture_event(reviewed, records)
    if not same_jti:
        duplicate.quote_jti = "00000000-0000-0000-0000-000000000000"
    original = booking_dao.stage_booking_record
    observed = []

    def insert_duplicate(db, record):
        if isinstance(record, ReservationChangeEvent):
            original(db, duplicate)
        try:
            return original(db, record)
        except IntegrityError as exc:
            observed.append(str(exc.orig))
            raise

    monkeypatch.setattr(booking_dao, "stage_booking_record", insert_duplicate)
    assert_conflict(engine, request)
    assert len(observed) == 1 and "UNIQUE constraint failed: reservation_change_events" in observed[0]


def test_real_foreign_key_failure_is_not_a_successful_retry(quote_app, monkeypatch):
    _, engine, _, _ = quote_app
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    request = confirmation(review(engine))
    original = booking_dao.stage_booking_record
    errors = []

    def invalid_event(db, record):
        if isinstance(record, ReservationChangeEvent):
            record.booking_payment_id = 999
        try:
            return original(db, record)
        except IntegrityError as exc:
            errors.append(str(exc.orig))
            raise

    monkeypatch.setattr(booking_dao, "stage_booking_record", invalid_event)
    assert_conflict(engine, request, expected=500)
    assert errors == ["FOREIGN KEY constraint failed"]


@pytest.mark.parametrize("conflict", [False, True])
def test_uniqueness_recovery_requires_matching_committed_token_and_request(quote_app, monkeypatch, conflict):
    _, engine, _, _ = quote_app
    reviewed = review(engine)
    request = confirmation(reviewed)
    winner = request
    if conflict:
        other = review(engine, check_in_date="2026-11-08", check_out_date="2026-11-10")
        claims = signing.decode_change_quote_claims(reviewed.quote_id)
        winner = confirmation(other, quote_id=resigned(other.quote_id, {"jti": claims.jti}))
    original_stage = booking_dao.stage_booking_record
    inject = {"fail": True, "winner_needed": False, "receipt": None}

    def fail_once(db, record):
        result = original_stage(db, record)
        if isinstance(record, ReservationChangeEvent) and inject["fail"]:
            inject["fail"] = False
            inject["winner_needed"] = True
            raise sqlite_unique_error("UNIQUE constraint failed: reservation_change_events.quote_jti")
        return result

    monkeypatch.setattr(booking_dao, "stage_booking_record", fail_once)
    with Session(engine) as db:
        original_rollback = db.rollback

        def rollback_then_competing_commit():
            original_rollback()
            if inject["winner_needed"]:
                inject["winner_needed"] = False
                inject["receipt"] = confirm(engine, winner)

        monkeypatch.setattr(db, "rollback", rollback_then_competing_commit)
        if conflict:
            with pytest.raises(HTTPException) as error:
                service.confirm_reservation_change(db, request, 1, 7, now=NOW)
            assert error.value.status_code == 409
        else:
            assert service.confirm_reservation_change(db, request, 1, 7, now=NOW) == inject["receipt"]
        assert not db.in_transaction()
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 1
        assert len(db.scalars(select(ReservationChangeEvent)).all()) == 1
        assert db.scalars(select(ReservationChangeEvent)).one().response_json == inject["receipt"]


@pytest.mark.parametrize("stage", ["provider", "lock_wait"])
def test_quote_expiry_is_rechecked_after_external_request_and_lock_wait(quote_app, monkeypatch, stage):
    _, engine, _, _ = quote_app
    request = confirmation(review(engine))
    clock = {"now": NOW}
    base_datetime = signing.datetime

    class Clock(base_datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"] if tz is not None else clock["now"].replace(tzinfo=None)

    monkeypatch.setattr(signing, "datetime", Clock)
    monkeypatch.setattr(reservation_change_validation, "datetime", Clock)
    if stage == "provider":
        original = hotel_service.revalidate_hotel

        def provider(context):
            fresh = original(context)
            clock["now"] += timedelta(minutes=10)
            return fresh

        monkeypatch.setattr(hotel_service, "revalidate_hotel", provider)
    else:
        original = booking_dao.lock_user_for_booking

        def acquire(db, user_id):
            result = original(db, user_id)
            clock["now"] += timedelta(minutes=10)
            return result

        monkeypatch.setattr(booking_dao, "lock_user_for_booking", acquire)
    assert_conflict(engine, request, now=None)


def test_completed_charge_allows_later_change_using_revised_obligation(quote_app):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.get(Payment, 1).amount = 100
        db.commit()
    first = confirm(engine, confirmation(review(engine)))
    with Session(engine) as db:
        # Prepared fixture only: this increment does not implement settlement.
        db.get(ReservationChangeAdjustment, first["adjustment"]["adjustment_id"]).status = "paid"
        db.get(Reservation, 1).revision += 1
        db.commit()
    second = review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")
    receipt = confirm(engine, confirmation(second))
    assert receipt["revision"] == 3 and receipt["previous_payment_obligation"] == "181.44"
    assert receipt["adjustment"]["amount"] == "90.72"
    with Session(engine) as db:
        assert db.get(Payment, 1).amount == 100
        assert db.get(ReservationChangeAdjustment, first["adjustment"]["adjustment_id"]).status == "paid"


def test_charge_state_is_rechecked_after_provider(quote_app, monkeypatch):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.get(Payment, 1).amount = 100
        db.commit()
    first = confirm(engine, confirmation(review(engine)))
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, first["adjustment"]["adjustment_id"]).status = "paid"
        db.commit()
    request = confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-10"))
    original = hotel_service.revalidate_hotel

    def provider(context):
        fresh = original(context)
        with Session(engine) as db:
            db.get(ReservationChangeAdjustment, first["adjustment"]["adjustment_id"]).status = "failed"
            db.commit()
        return fresh

    monkeypatch.setattr(hotel_service, "revalidate_hotel", provider)
    with pytest.raises(HTTPException) as error:
        confirm(engine, request)
    assert error.value.status_code == 409
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 1
        assert len(db.scalars(select(ReservationChangeEvent)).all()) == 1
        assert db.get(ReservationChangeAdjustment, first["adjustment"]["adjustment_id"]).status == "failed"


def test_locked_statements_refresh_state_and_order_child_rows(quote_app):
    from sqlalchemy.dialects.mysql import dialect

    _, engine, _, _ = quote_app
    request = confirmation(review(engine))
    with Session(engine) as db:
        locked = []

        def capture(orm_state):
            if getattr(orm_state.statement, "_for_update_arg", None) is not None:
                locked.append((str(orm_state.statement.compile(dialect=dialect())), orm_state.load_options._populate_existing))

        event.listen(db, "do_orm_execute", capture)
        service.confirm_reservation_change(db, request, 1, 7, now=NOW)
    assert len(locked) == 4
    assert all(sql.endswith("FOR UPDATE") for sql, _ in locked)
    assert "users.user_id" in locked[0][0] and "reservations.reservation_id" in locked[1][0]
    assert "ORDER BY payments.payment_id" in locked[2][0]
    assert "ORDER BY reservation_change_adjustments.adjustment_id" in locked[3][0]
    assert all(refresh for _, refresh in locked[1:])


def test_cent_equivalent_acknowledgements_have_identical_idempotent_receipt(quote_app):
    _, engine, calls, _ = quote_app
    reviewed = review(engine)
    receipt = confirm(engine, confirmation(reviewed, price_per_night=80 + 1e-12, accepted_payment_amount=181.44 + 1e-12))
    assert confirm(engine, confirmation(reviewed)) == receipt and len(calls) == 2


def test_competing_creation_and_change_share_user_serialization(threaded_database, monkeypatch):
    from app.schemas.booking_schema import BookingRequest

    engine = threaded_database
    reviewed = review(engine)
    create_request = BookingRequest(
        hotel_token="property-B", guest_full_name="Booking Guest", guest_email="guest@example.com",
        q="San Jose hotels", adults=3, children=1,
        check_in_date="2026-11-04", check_out_date="2026-11-06",
        price_per_night=80, accepted_payment_amount=181.44,
    )
    barrier = Barrier(2)
    original = hotel_service.revalidate_hotel
    monkeypatch.setattr(hotel_service, "revalidate_hotel", lambda context: (original(context), barrier.wait(timeout=10))[0])

    def attempt(create):
        try:
            if create:
                with Session(engine) as db:
                    return booking_service.create_booking(db, create_request, 7)
            return confirm(engine, confirmation(reviewed))
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [True, False]))
    assert sum(not isinstance(value, int) for value in results) == 1
    assert any(value in (400, 409) for value in results if isinstance(value, int))
    with Session(engine) as db:
        overlapping = db.scalars(select(Reservation).where(
            Reservation.user_id == 7, Reservation.status != "cancelled",
            Reservation.check_in_date < date(2026, 11, 6), Reservation.check_out_date > date(2026, 11, 4),
        )).all()
        assert len(overlapping) == 1


@pytest.mark.parametrize("field,value", [("new_payment_obligation", Decimal("99.99")), ("new_room_type_id", 2), ("booking_payment_id", 999)])
def test_inconsistent_latest_financial_history_fails_closed(quote_app, field, value):
    _, engine, _, _ = quote_app
    confirm(engine, confirmation(review(engine)))
    with Session(engine) as db:
        change = db.scalars(select(ReservationChangeEvent)).one()
        # Deliberately corrupt isolated fixtures to prove the service fails closed.
        setattr(change, field, value)
        db.commit()
    request = confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-10"))
    assert_conflict(engine, request)


def test_expired_unconsumed_historical_input_cannot_mutate(quote_app):
    _, engine, calls, _ = quote_app
    reviewed = review(engine)
    historical = ReservationChangeReceiptRequest(**confirmation(reviewed).model_dump())
    assert_conflict(engine, historical, now=NOW + timedelta(days=100))
    assert len(calls) == 1


def test_room_association_reuses_matching_rate_record(quote_app):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.add(RoomType(room_type_id=3, hotel_id=1, type_name="Lowest available rate",
                        description="Provider: Trusted provider", price_per_night=80))
        db.commit()
    receipt = confirm(engine, confirmation(review(engine)))
    assert receipt["room_type_id"] == 3
    with Session(engine) as db:
        assert len(db.scalars(select(RoomType)).all()) == 3
        assert db.get(RoomType, 1).price_per_night == 100
