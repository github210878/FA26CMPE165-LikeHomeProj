"""Atomic original-payment rewards with synthetic SQLite and modeled transactions.

The mutex tests model application transactions, not MySQL/InnoDB row locks.
No external funds, provider requests, or historical reward reconciliation occur.
"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import httpx
import pytest
import requests
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.user import User
from app.repositories import booking_dao
from app.services import booking_service
from test_payment_integration import (
    headers,
    payment_app as payment_app,
    serialized_payment_store as serialized_payment_store,
)


def persisted_state(engine):
    with Session(engine) as db:
        return {
            "payments": [(p.payment_id, p.payment_status, p.amount)
                         for p in db.scalars(select(Payment).order_by(Payment.payment_id))],
            "users": [(u.user_id, u.status, u.reward_points)
                      for u in db.scalars(select(User).order_by(User.user_id))],
            "reservations": [(r.reservation_id, r.user_id, r.status)
                             for r in db.scalars(select(Reservation).order_by(Reservation.reservation_id))],
        }


@pytest.mark.parametrize(("amount", "points"), [
    (0, 0), (0.01, 0), (0.99, 0), (1, 1), (1.01, 1), (1.99, 1),
    (19.99, 19), (100.00, 100), (226.80, 226), (99999999.99, 99999999),
])
def test_pending_payment_awards_whole_usd_once(payment_app, amount, points):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(Payment, 1).amount = amount
        db.get(User, 7).reward_points = 10
        db.commit()
    first = client.post("/bookings/pay/1", headers=headers())
    second = client.post("/bookings/pay/1", headers=headers())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {
        "payment_id": 1, "reservation_id": 1, "amount": amount,
        "payment_type": "booking", "payment_status": "paid",
    }
    with Session(engine) as db:
        assert type(db.get(User, 7).reward_points) is int
        assert db.get(User, 7).reward_points == 10 + points
        assert db.get(User, 8).reward_points == 0
        assert db.query(Payment).count() == 1


def test_reward_database_failure_rolls_back_payment_and_retry_awards_once(payment_app):
    client, engine = payment_app
    before = persisted_state(engine)
    attempts = []

    def fail_reward_write(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("UPDATE USERS"):
            attempts.append("reward update")
            raise SQLAlchemyError("synthetic reward write failure")

    event.listen(engine, "before_cursor_execute", fail_reward_write)
    try:
        response = client.post("/bookings/pay/1", headers=headers())
    finally:
        event.remove(engine, "before_cursor_execute", fail_reward_write)
    assert attempts == ["reward update"]
    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to record payment"}
    assert persisted_state(engine) == before
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    with Session(engine) as db:
        assert db.get(Payment, 1).payment_status == "paid"
        assert db.get(User, 7).reward_points == 226


def test_commit_failure_rolls_back_already_flushed_payment_and_rewards(payment_app, monkeypatch):
    _, engine = payment_app
    before = persisted_state(engine)
    staged = []
    with Session(engine) as db:
        def fail_commit():
            db.flush()
            staged.append((db.get(Payment, 1).payment_status, db.get(User, 7).reward_points))
            raise SQLAlchemyError("synthetic atomic commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(HTTPException) as error:
            booking_service.pay_booking_payment(db, 1, 7)
        assert error.value.status_code == 500
        assert isinstance(error.value.__cause__, SQLAlchemyError)
    assert staged == [("paid", 226)]
    assert persisted_state(engine) == before


def test_payment_write_failure_also_rolls_back_rewards(payment_app):
    client, engine = payment_app
    before = persisted_state(engine)

    def fail_payment_write(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("UPDATE PAYMENTS"):
            raise SQLAlchemyError("synthetic payment write failure")

    event.listen(engine, "before_cursor_execute", fail_payment_write)
    try:
        response = client.post("/bookings/pay/1", headers=headers())
    finally:
        event.remove(engine, "before_cursor_execute", fail_payment_write)
    assert response.status_code == 500
    assert persisted_state(engine) == before


@pytest.mark.parametrize("missing", [True, False], ids=["missing-user", "inactive-user"])
def test_missing_or_inactive_user_cannot_commit_payment(payment_app, missing):
    client, engine = payment_app
    with Session(engine) as db:
        user = db.get(User, 7)
        if missing:
            db.delete(user)  # Synthetic orphan: ORM SQLite lacks production FKs.
        else:
            user.status = "deleted"
        db.commit()
    before = persisted_state(engine)
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 401
    # Also verify the service's locked recheck, without relying on route auth.
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            booking_service.pay_booking_payment(db, 1, 7)
        assert error.value.status_code == 401
        assert error.value.headers == {"WWW-Authenticate": "Bearer"}
    assert persisted_state(engine) == before


@pytest.mark.parametrize(("user_id", "role", "status"), [(8, "user", 404), (7, "partner", 401)])
def test_unauthorized_payment_cannot_change_either_customers_rewards(payment_app, user_id, role, status):
    client, engine = payment_app
    before = persisted_state(engine)
    assert client.post("/bookings/pay/1", headers=headers(user_id, role)).status_code == status
    assert persisted_state(engine) == before


def test_locked_reservation_ownership_is_authoritative(payment_app, monkeypatch):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(Reservation, 1).user_id = 8
        db.commit()
    before = persisted_state(engine)
    # Emulate an outdated ownership precheck, without bypassing locked checks.
    monkeypatch.setattr(booking_dao, "get_owned_payment_reservation_id", lambda *_: 1)
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 404
    assert persisted_state(engine) == before


@pytest.mark.parametrize("payment_status", ["pending", "paid"])
def test_cancelled_reservation_cannot_award_points(payment_app, payment_status):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(Reservation, 1).status = "cancelled"
        db.get(Payment, 1).payment_status = payment_status
        db.commit()
    before = persisted_state(engine)
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 409
    assert persisted_state(engine) == before


@pytest.mark.parametrize("status", ["confirmed", "completed"])
@pytest.mark.parametrize("balance", [0, 50])
def test_historical_paid_rows_get_no_automatic_catchup(payment_app, monkeypatch, status, balance):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.get(Reservation, 1).status = status
        db.get(User, 7).reward_points = balance
        db.commit()
    before = persisted_state(engine)

    def forbidden_award(*_args, **_kwargs):
        pytest.fail("Historical/repeated paid requests must never award rewards")

    monkeypatch.setattr(booking_dao, "add_reward_points_to_user", forbidden_award)
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    assert persisted_state(engine) == before


@pytest.mark.parametrize("history", ["duplicate-pending", "duplicate-paid", "duplicate-failed", "cancellation-only", "extra-cancellation"])
def test_multiple_or_malformed_booking_payments_fail_closed(payment_app, history):
    client, engine = payment_app
    with Session(engine) as db:
        if history == "cancellation-only":
            db.get(Payment, 1).payment_type = "cancellation"
        else:
            db.add(Payment(payment_id=2, reservation_id=1, amount=42,
                           payment_type="cancellation" if history == "extra-cancellation" else "booking",
                           payment_status=history.removeprefix("duplicate-") if history.startswith("duplicate-") else "pending"))
        db.commit()
    before = persisted_state(engine)
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 409
    if history != "cancellation-only":
        assert client.post("/bookings/pay/2", headers=headers()).status_code == 409
    assert persisted_state(engine) == before


@pytest.mark.parametrize("amount", [
    -0.01, float("nan"), float("inf"), float("-inf"), 100000000,
    0.001, Decimal("1E+999"), "226.80", None, True,
], ids=["negative", "nan", "inf", "negative-inf", "out-of-range", "off-cent", "huge", "string", "missing", "boolean"])
def test_invalid_locked_money_rejects_without_writes(payment_app, monkeypatch, amount):
    client, engine = payment_app
    before = persisted_state(engine)
    original = booking_dao.lock_booking_payment

    def invalid_locked_row(*args):
        payment = original(*args)
        # Simulate malformed persisted/driver state without depending on SQLite
        # coercion of NaN/NULL into its different column constraints.
        set_committed_value(payment, "amount", amount)
        return payment

    monkeypatch.setattr(booking_dao, "lock_booking_payment", invalid_locked_row)
    response = client.post("/bookings/pay/1", headers=headers())
    assert response.status_code == 409
    assert response.json() == {"detail": "Payment amount is unsupported"}
    assert persisted_state(engine) == before


@pytest.mark.parametrize("balance", [-1, 1.5, None, True, "10", 2147483648])
def test_invalid_locked_balance_rejects_without_writes(payment_app, monkeypatch, balance):
    client, engine = payment_app
    before = persisted_state(engine)
    original = booking_dao.lock_active_user_for_payment

    def invalid_locked_user(*args):
        user = original(*args)
        # Model a malformed loaded value, not a dirty write that an autoflush
        # would send to SQLite before the service can validate the balance.
        set_committed_value(user, "reward_points", balance)
        return user

    monkeypatch.setattr(booking_dao, "lock_active_user_for_payment", invalid_locked_user)
    response = client.post("/bookings/pay/1", headers=headers())
    assert response.status_code == 409
    assert response.json() == {"detail": "Reward balance is unsupported"}
    assert persisted_state(engine) == before


def test_reward_balance_overflow_rejects_atomically(payment_app):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(User, 7).reward_points = 2147483647 - 225
        db.commit()
    before = persisted_state(engine)
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 409
    assert persisted_state(engine) == before


def test_reward_balance_can_reach_signed_int_max_exactly(payment_app):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(User, 7).reward_points = 2147483647 - 226
        db.commit()
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    with Session(engine) as db:
        assert db.get(User, 7).reward_points == 2147483647
        assert db.get(Payment, 1).payment_status == "paid"


def test_reward_dao_stages_without_owning_transaction(payment_app, monkeypatch):
    _, engine = payment_app
    before = persisted_state(engine)

    def forbidden_boundary(*_args, **_kwargs):
        pytest.fail("Reward DAO must leave transaction boundaries to its caller")

    with Session(engine) as db:
        user = booking_dao.lock_active_user_for_payment(db, 7)
        booking_dao.lock_owned_reservation(db, 1, 7)
        payment = booking_dao.lock_booking_payment(db, 1, 1)
        payment.payment_status = "paid"
        with monkeypatch.context() as scoped:
            for method in ("commit", "rollback", "refresh"):
                scoped.setattr(db, method, forbidden_boundary)
            booking_dao.add_reward_points_to_user(db, user, 226)
        assert user.reward_points == 226
        db.rollback()
    assert persisted_state(engine) == before


def test_fresh_user_balance_replaces_cached_precheck_state(payment_app):
    _, engine = payment_app
    with Session(engine) as stale:
        old = stale.get(User, 7)
        assert old.reward_points == 0
        with Session(engine) as writer:
            writer.get(User, 7).reward_points = 100
            writer.commit()
        assert old.reward_points == 0
        assert booking_service.pay_booking_payment(stale, 1, 7).payment_status == "paid"
    with Session(engine) as db:
        assert db.get(User, 7).reward_points == 326


def test_emitted_lock_queries_follow_user_reservation_payment_id_order(payment_app):
    _, engine = payment_app
    locked_sql = []
    with Session(engine) as db:
        def capture_lock(execution):
            statement = execution.statement
            if getattr(statement, "_for_update_arg", None) is not None:
                locked_sql.append(str(statement.compile(dialect=mysql.dialect())))

        event.listen(db, "do_orm_execute", capture_lock)
        booking_service.pay_booking_payment(db, 1, 7)
    assert len(locked_sql) == 3
    assert "FROM users" in locked_sql[0] and "users.status" in locked_sql[0]
    assert "FROM reservations" in locked_sql[1] and "reservations.user_id" in locked_sql[1]
    assert "FROM payments" in locked_sql[2]
    assert "ORDER BY payments.payment_id" in locked_sql[2]
    assert all("FOR UPDATE" in sql for sql in locked_sql)


def test_modeled_same_payment_requests_award_once(serialized_payment_store):
    store = serialized_payment_store
    start = Barrier(5)

    def pay(_):
        db = store.Transaction()
        start.wait(timeout=5)
        try:
            return booking_service.pay_booking_payment(db, 1, 7).payment_status
        finally:
            db.rollback()

    with ThreadPoolExecutor(max_workers=5) as pool:
        assert list(pool.map(pay, range(5))) == ["paid"] * 5
    assert store.commits == ["paid"]
    assert store.awards == [226]
    assert store.user.reward_points == 226
    assert store.payments[1].payment_status == "paid"


def test_modeled_two_bookings_retain_both_awards(serialized_payment_store):
    store = serialized_payment_store
    row_type = type(store.payments[1])
    store.payments[2] = row_type(payment_id=2, reservation_id=2, amount=19.99,
                               payment_type="booking", payment_status="pending")
    start = Barrier(2)

    def pay(payment_id):
        db = store.Transaction()
        start.wait(timeout=5)
        try:
            return booking_service.pay_booking_payment(db, payment_id, 7).payment_status
        finally:
            db.rollback()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(pay, [1, 2])) == ["paid", "paid"]
    assert store.commits == ["paid", "paid"]
    assert sorted(store.awards) == [19, 226]
    assert store.user.reward_points == 245
    assert all(row.payment_status == "paid" for row in store.payments.values())


@pytest.mark.parametrize("failure", ["flush", "commit"])
def test_modeled_rollback_discards_staged_award_before_retry(serialized_payment_store, failure):
    store = serialized_payment_store
    db = store.Transaction()
    setattr(db, "fail_" + failure, True)
    with pytest.raises(HTTPException) as error:
        booking_service.pay_booking_payment(db, 1, 7)
    assert error.value.status_code == 500
    assert store.commits == store.awards == []
    assert store.user.reward_points == 0
    assert store.payments[1].payment_status == "pending"
    assert not db.owns_lock
    retry = store.Transaction()
    assert booking_service.pay_booking_payment(retry, 1, 7).payment_status == "paid"
    assert store.awards == [226]
    assert store.user.reward_points == 226


def test_successful_commit_with_lost_response_retries_without_new_award(payment_app, monkeypatch):
    client, engine = payment_app
    with Session(engine) as db:
        original = db.commit

        def committed_but_response_lost():
            original()
            raise SQLAlchemyError("synthetic acknowledgement loss after durable commit")

        monkeypatch.setattr(db, "commit", committed_but_response_lost)
        with pytest.raises(HTTPException) as error:
            booking_service.pay_booking_payment(db, 1, 7)
        assert error.value.status_code == 500
    with Session(engine) as db:
        assert db.get(Payment, 1).payment_status == "paid"
        assert db.get(User, 7).reward_points == 226
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    with Session(engine) as db:
        assert db.get(User, 7).reward_points == 226


def test_pay_then_cancel_preserves_fee_and_adds_no_new_award_or_clawback(payment_app):
    client, engine = payment_app
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    cancelled = client.post("/bookings/cancel-booking/1", headers=headers())
    assert cancelled.status_code == 200
    assert cancelled.json()["cancellation_amount"] == 42
    assert cancelled.json()["booking_payment_status"] == "refunded"
    assert client.post("/bookings/pay/2", headers=headers()).status_code == 409
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 409
    with Session(engine) as db:
        assert db.get(User, 7).reward_points == 226
        assert db.get(Payment, 2).payment_status == "pending"


def test_payment_and_retry_never_collect_external_funds(payment_app, monkeypatch):
    client, engine = payment_app
    calls = []

    def forbidden_external(*_args, **_kwargs):
        calls.append("external call")
        raise AssertionError("Payment must remain internal accounting")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden_external)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden_external)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_external)
    monkeypatch.setattr(booking_service.hotel_service, "revalidate_hotel", forbidden_external)
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 200
    assert calls == []
    with Session(engine) as db:
        assert db.get(User, 7).reward_points == 226
