"""Isolated HTTP and transaction tests for the internal payment contract."""

from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
from app.services import booking_service
from app.utilities import auth


@pytest.fixture
def payment_app(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            User(user_id=7, email="owner@example.test", password_hash="hash", status="active"),
            User(user_id=8, email="other@example.test", password_hash="hash", status="active"),
        ])
        hotel = Hotel(name="Hotel", hotel_token="property-1")
        db.add(hotel)
        db.flush()
        room = RoomType(hotel_id=hotel.hotel_id, type_name="Queen", price_per_night=100)
        db.add(room)
        db.flush()
        reservation = Reservation(user_id=7, room_type_id=room.room_type_id,
                                  check_in_date=date(2026, 11, 1), check_out_date=date(2026, 11, 3),
                                  total_price=210, status="confirmed")
        db.add(reservation)
        db.flush()
        db.add(Payment(reservation_id=reservation.reservation_id, amount=226.80,
                       payment_type="booking", payment_status="pending"))
        db.commit()

    app = FastAPI()
    app.include_router(booking_router)

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "test-secret-for-payment-integration")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    yield TestClient(app), engine
    engine.dispose()


def headers(subject_id=7, subject_type="user"):
    token = auth.create_access_token(subject_id, subject_type=subject_type)
    return {"Authorization": f"Bearer {token}"}


def test_owner_pays_persisted_amount_once_and_reads_typed_details(payment_app):
    client, engine = payment_app
    before = client.get("/bookings/get-payment-details/1", headers=headers())
    assert before.status_code == 200
    assert before.json() == {"payment_id": 1, "reservation_id": 1, "amount": 226.8,
                             "payment_type": "booking", "payment_status": "pending"}

    rejected = client.post("/bookings/pay/1", headers=headers(), json={"amount": 0.01, "payment_status": "refunded", "user_id": 8})
    assert rejected.status_code == 422
    first = client.post("/bookings/pay/1", headers=headers())
    second = client.post("/bookings/pay/1", headers=headers())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {**before.json(), "payment_status": "paid"}
    assert client.get("/bookings/get-all-payments", headers=headers()).json() == [first.json()]
    with Session(engine) as db:
        payments = db.scalars(select(Payment)).all()
        assert len(payments) == 1
        assert payments[0].amount == 226.8
        assert payments[0].payment_status == "paid"


def test_nonowner_partner_and_missing_payment_cannot_read_or_pay(payment_app):
    client, _ = payment_app
    for method, path in [("get", "/bookings/get-payment-details/1"),
                         ("post", "/bookings/pay/1")]:
        nonowner = getattr(client, method)(path, headers=headers(8))
        if method == "post":
            assert nonowner.status_code == 404
        else:
            assert nonowner.status_code == 200 and nonowner.json() is None
        assert getattr(client, method)(path, headers=headers(7, "partner")).status_code == 401
        assert getattr(client, method)(path).status_code == 401
    assert client.post("/bookings/pay/999", headers=headers()).status_code == 404
    assert client.get("/bookings/get-all-payments", headers=headers(8)).json() == []


@pytest.mark.parametrize("payment_status", ["failed", "refunded"])
def test_terminal_payment_states_reject_pay(payment_app, payment_status):
    client, engine = payment_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = payment_status
        db.commit()
    response = client.post("/bookings/pay/1", headers=headers())
    assert response.status_code == 409
    with Session(engine) as db:
        assert db.get(Payment, 1).payment_status == payment_status


def test_cancellation_charge_cannot_use_booking_pay_route(payment_app):
    client, engine = payment_app
    with Session(engine) as db:
        db.add(Payment(reservation_id=1, amount=42, payment_type="cancellation", payment_status="pending"))
        db.commit()
    assert client.post("/bookings/pay/2", headers=headers()).status_code == 409
    with Session(engine) as db:
        assert db.get(Payment, 2).payment_status == "pending"


def test_pending_booking_cancellation_does_not_claim_refund(payment_app):
    client, engine = payment_app
    response = client.post("/bookings/cancel-booking/1", headers=headers())
    assert response.status_code == 200
    assert response.json()["booking_payment_status"] == "pending"
    assert response.json()["cancellation_payment_status"] == "pending"
    assert response.json()["cancellation_amount"] == 42
    assert client.post("/bookings/pay/1", headers=headers()).status_code == 409
    with Session(engine) as db:
        assert db.get(Payment, 1).payment_status == "pending"
        assert db.get(Payment, 2).payment_type == "cancellation"


def test_failed_payment_commit_rolls_back(payment_app, monkeypatch):
    _, engine = payment_app
    with Session(engine) as db:
        def fail_commit():
            db.flush()
            raise SQLAlchemyError("simulated failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(Exception) as caught:
            booking_service.pay_booking_payment(db, 1, 7)
        assert caught.value.status_code == 500
        assert caught.value.detail == "Failed to record payment"
    with Session(engine) as db:
        assert db.get(Payment, 1).payment_status == "pending"


def test_payment_locks_reservation_then_existing_payment(payment_app, monkeypatch):
    _, engine = payment_app
    order = []
    from app.repositories import booking_dao

    original_reservation = booking_dao.lock_owned_reservation
    original_payment = booking_dao.lock_booking_payment

    def lock_reservation(*args):
        order.append("reservation")
        return original_reservation(*args)

    def lock_payment(*args):
        order.append("payment")
        return original_payment(*args)

    monkeypatch.setattr(booking_dao, "lock_owned_reservation", lock_reservation)
    monkeypatch.setattr(booking_dao, "lock_booking_payment", lock_payment)
    with Session(engine) as db:
        assert booking_service.pay_booking_payment(db, 1, 7).payment_status == "paid"
    assert order == ["reservation", "payment"]


def test_only_first_pay_commits(payment_app, monkeypatch):
    _, engine = payment_app
    with Session(engine) as db:
        original_commit = db.commit
        commits = 0

        def count_commit():
            nonlocal commits
            commits += 1
            return original_commit()

        monkeypatch.setattr(db, "commit", count_commit)
        assert booking_service.pay_booking_payment(db, 1, 7).payment_status == "paid"
        assert booking_service.pay_booking_payment(db, 1, 7).payment_status == "paid"
        assert commits == 1


def test_two_serialized_pay_attempts_share_one_transition(monkeypatch):
    """Model the InnoDB row wait; only the first waiter changes the existing row."""
    from app.repositories import booking_dao

    row_lock = Lock()
    start = Barrier(2)
    commits = []
    payment = SimpleNamespace(payment_id=1, reservation_id=1, amount=226.8,
                              payment_type="booking", payment_status="pending")
    reservation = SimpleNamespace(status="confirmed", revision=0)

    class Transaction:
        def __init__(self):
            self.owns_lock = False

        def rollback(self):
            if self.owns_lock:
                row_lock.release()
                self.owns_lock = False

        def commit(self):
            commits.append(payment.payment_status)
            self.rollback()

    def lock_reservation(db, reservation_id, user_id):
        row_lock.acquire()
        db.owns_lock = True
        return reservation

    monkeypatch.setattr(booking_dao, "get_owned_payment_reservation_id", lambda *_: 1)
    monkeypatch.setattr(booking_dao, "lock_owned_reservation", lock_reservation)
    monkeypatch.setattr(booking_dao, "lock_booking_payment", lambda *_: payment)

    def pay():
        db = Transaction()
        start.wait()
        try:
            return booking_service.pay_booking_payment(db, 1, 7)
        finally:
            db.rollback()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: pay(), range(2)))
    assert [result.payment_status for result in results] == ["paid", "paid"]
    assert commits == ["paid"]
    assert payment.payment_status == "paid"
    assert reservation.revision == 1
