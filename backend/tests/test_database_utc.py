"""Offline connection/default contracts; no MySQL socket or environment changes."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.config.database import Base, _initialize_mysql_utc, create_app_engine
from app.models import Hotel, Payment, Reservation, RoomType, User
from app.utilities import timestamps


def test_mysql_factory_registers_initializer_without_connecting():
    engine = create_app_engine("mysql+pymysql://synthetic:unused@127.0.0.1:1/unused")
    try:
        assert event.contains(engine, "connect", _initialize_mysql_utc)
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure", [False, True])
def test_initializer_closes_cursor_and_never_commits_or_hides_errors(failure):
    statements, closed = [], []

    def execute(statement):
        statements.append(statement)
        if failure:
            raise RuntimeError("Synthetic timezone initialization failure")

    def forbidden():
        raise AssertionError("UTC initialization must not commit or roll back")

    cursor = SimpleNamespace(execute=execute, close=lambda: closed.append(True))
    connection = SimpleNamespace(cursor=lambda: cursor, commit=forbidden, rollback=forbidden)
    if failure:
        with pytest.raises(RuntimeError, match="initialization failure"):
            _initialize_mysql_utc(connection, None)
    else:
        _initialize_mysql_utc(connection, None)
    assert statements == ["SET SESSION time_zone = '+00:00'"] and closed == [True]


def test_sqlite_has_no_mysql_initializer_and_retains_rollback_behavior():
    engine = create_app_engine("sqlite://")
    try:
        assert not event.contains(engine, "connect", _initialize_mysql_utc)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE probe (value INTEGER)"))
        with engine.connect() as connection:
            connection.execute(text("INSERT INTO probe VALUES (1)"))
            connection.rollback()
            assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar_one() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("offset", [-7, 5.5])
def test_future_legacy_defaults_are_utc_even_with_non_utc_host_clock(monkeypatch, offset):
    instant = datetime(2026, 10, 10, 12, 34, 56, 123456, tzinfo=timezone.utc)

    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return instant.astimezone(tz)
            return instant.astimezone(timezone(timedelta(hours=offset))).replace(tzinfo=None)

    monkeypatch.setattr(timestamps, "datetime", HostClock)
    engine = create_app_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            user = User(email="utc-default@example.test", password_hash="synthetic")
            hotel = Hotel(name="Synthetic hotel", hotel_token="utc-default")
            db.add_all([user, hotel])
            db.flush()
            room = RoomType(hotel_id=hotel.hotel_id, type_name="Synthetic", price_per_night=100)
            db.add(room)
            db.flush()
            reservation = Reservation(user_id=user.user_id, room_type_id=room.room_type_id,
                                      check_in_date=date(2030, 11, 1), check_out_date=date(2030, 11, 3),
                                      total_price=210, status="confirmed")
            db.add(reservation)
            db.flush()
            payment = Payment(reservation_id=reservation.reservation_id, amount=226.8,
                              payment_type="booking", payment_status="pending")
            db.add(payment)
            db.commit()
            for row in (user, reservation, payment):
                db.refresh(row)
                assert row.created_at == instant.replace(tzinfo=None)
                assert row.created_at.tzinfo is None
            # Reading/updating a historical explicit naive value never reinterprets it.
            historical = datetime(2020, 1, 1, 9)
            payment.created_at = historical
            db.commit()
            payment.payment_status = "paid"
            db.commit()
            db.refresh(payment)
            assert payment.created_at == historical
    finally:
        engine.dispose()
