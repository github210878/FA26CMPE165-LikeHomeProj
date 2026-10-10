"""Opt-in UTC checks against the runner's verified disposable MySQL only."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pymysql
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DataError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from test_mysql57_contract import app, engine, make_stay, mysql57, provider, review, stay


@pytest.fixture
def utc_engine(mysql57):
    configured = mysql57.engine(mysql57.upgrade, pool_size=2, max_overflow=0)
    try:
        yield configured
    finally:
        configured.dispose()


def settings(connection):
    return connection.execute(text(
        "SELECT CONNECTION_ID(), @@session.time_zone, @@global.time_zone, "
        "@@session.sql_mode, @@global.sql_mode, @@autocommit"
    )).one()


@contextmanager
def probe_table(configured):
    # Fresh names and explicit cleanup isolate schema/session mutation per test.
    name = "us72_utc_probe_" + uuid4().hex
    with configured.begin() as connection:
        connection.execute(text(f"CREATE TABLE `{name}` ("
            "id INT PRIMARY KEY AUTO_INCREMENT, "
            "dt DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), "
            "ts TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), "
            "amount DECIMAL(10,2) NOT NULL DEFAULT 1, day DATE NULL) ENGINE=InnoDB"))
    try:
        yield name
    finally:
        with configured.begin() as connection:
            connection.execute(text(f"DROP TABLE `{name}`"))
            assert connection.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=:name"
            ), {"name": name}).scalar_one() == 0


@pytest.fixture
def probe(utc_engine):
    with probe_table(utc_engine) as name:
        yield name


def test_new_physical_connections_initialize_once_and_pool_reuse_is_utc(utc_engine, mysql57, monkeypatch):
    statements = []
    execute = pymysql.cursors.Cursor.execute

    def record(cursor, query, args=None):
        if query == "SET SESSION time_zone = '+00:00'":
            statements.append(query)
        return execute(cursor, query, args)

    monkeypatch.setattr(pymysql.cursors.Cursor, "execute", record)
    with mysql57.connect(initialize_utc=False) as control:
        with control.cursor() as cursor:
            cursor.execute("SELECT @@session.time_zone, @@global.time_zone, @@sql_mode")
            inherited, global_zone, sql_mode = cursor.fetchone()
    with utc_engine.connect() as connection:
        assert not connection.in_transaction()
        before = settings(connection)
    for _ in range(3):
        with utc_engine.connect() as connection:
            reused = settings(connection)
            assert reused == before
    assert statements == ["SET SESSION time_zone = '+00:00'"]
    assert before[1] == "+00:00" and before[2] == global_zone
    assert set(before[3].split(",")) == set(sql_mode.split(","))
    assert before[5] == 0
    mysql57.evidence["utc_connections"] = {
        "inherited_session": inherited, "application_session": before[1],
        "global_time_zone": global_zone, "sql_mode": before[3],
        "single_initializer_per_physical_connection": True, "pooled_reuse": True,
    }


def test_two_simultaneous_pool_connections_are_independently_utc(utc_engine):
    with utc_engine.connect() as first, utc_engine.connect() as second:
        assert not first.in_transaction() and not second.in_transaction()
        a, b = settings(first), settings(second)
        assert a[0] != b[0] and a[1] == b[1] == "+00:00"
        assert a[2:] == b[2:]


def test_invalidated_connection_is_replaced_and_reinitialized(utc_engine, mysql57):
    with utc_engine.connect() as connection:
        before = settings(connection)
        connection.execute(text("SET SESSION time_zone = '+05:30'"))
        assert settings(connection)[1] == "+05:30"
        connection.invalidate()
    with utc_engine.connect() as connection:
        after = settings(connection)
        assert after[0] != before[0]
        assert after[1] == "+00:00" and after[2:] == before[2:]
    mysql57.evidence["utc_reconnect"] = "new physical connection initialized to +00:00"


def test_pre_ping_reconnects_a_server_closed_session_and_reinitializes_utc(utc_engine, mysql57):
    with utc_engine.connect() as connection:
        before = settings(connection)
        connection.execute(text("SET SESSION time_zone='+05:30'"))
    # Kill only this test's idle connection on the identity-verified disposable server.
    with mysql57.connect(mysql57.upgrade) as control:
        with control.cursor() as cursor:
            cursor.execute(f"KILL CONNECTION {before[0]}")
    with utc_engine.connect() as connection:
        after = settings(connection)
        assert after[0] != before[0] and after[1] == "+00:00"
        assert after[2:] == before[2:]
    mysql57.evidence["utc_pre_ping_reconnect"] = True


def test_server_defaults_are_utc_with_microseconds(utc_engine, probe):
    with utc_engine.begin() as connection:
        before = connection.execute(text("SELECT UTC_TIMESTAMP(6)")).scalar_one()
        connection.execute(text(f"INSERT INTO `{probe}` () VALUES ()"))
        row = connection.execute(text(f"SELECT dt,ts FROM `{probe}`")).one()
        after = connection.execute(text("SELECT UTC_TIMESTAMP(6)")).scalar_one()
        assert before <= row.dt == row.ts <= after
        assert row.dt.tzinfo is None and row.ts.tzinfo is None


@pytest.mark.parametrize("offset", [-7, 5.5])
def test_datetime_roundtrip_is_stable_while_timestamp_display_converts(utc_engine, probe, offset):
    instant = datetime(2026, 10, 10, 12, 34, 56, 123456)
    zone = "-07:00" if offset == -7 else "+05:30"
    with utc_engine.begin() as connection:
        connection.execute(text(f"INSERT INTO `{probe}` (dt,ts) VALUES (:value,:value)"), {"value": instant})
    with utc_engine.connect() as connection:
        utc = connection.execute(text(f"SELECT dt,ts,UNIX_TIMESTAMP(ts) AS epoch FROM `{probe}`")).one()
        connection.execute(text("SET SESSION time_zone=:zone"), {"zone": zone})
        shifted = connection.execute(text(f"SELECT dt,ts,UNIX_TIMESTAMP(ts) AS epoch FROM `{probe}`")).one()
        assert utc.dt == utc.ts == shifted.dt == instant
        assert shifted.ts == instant + timedelta(hours=offset)
        assert utc.epoch == shifted.epoch
        connection.execute(text("SET SESSION time_zone='+00:00'"))


def test_utc_connection_initialization_does_not_commit_transaction_writes(utc_engine, probe):
    with utc_engine.connect() as connection:
        assert not connection.in_transaction()
        transaction = connection.begin()
        connection.execute(text(f"INSERT INTO `{probe}` (amount) VALUES (12.34)"))
        # A second physical connection initializes UTC while this write is pending.
        with utc_engine.connect() as observer:
            assert settings(observer)[1] == "+00:00"
            assert observer.execute(text(f"SELECT COUNT(*) FROM `{probe}`")).scalar_one() == 0
        transaction.rollback()
    with utc_engine.connect() as observer:
        assert observer.execute(text(f"SELECT COUNT(*) FROM `{probe}`")).scalar_one() == 0


@pytest.mark.parametrize("mode", [
    "STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION",
    "STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,NO_ENGINE_SUBSTITUTION",
    "NO_ENGINE_SUBSTITUTION",
])
def test_initializer_preserves_session_sql_mode_and_exposes_strict_mode_differences(mysql57, mode):
    configured = mysql57.engine(mysql57.upgrade, pool_size=1, max_overflow=0,
                               connect_args={"init_command": f"SET SESSION sql_mode='{mode}'"})
    try:
        with probe_table(configured) as name, configured.connect() as connection:
            observed = settings(connection)
            assert observed[1] == "+00:00"
            assert set(observed[3].split(",")) == set(mode.split(","))
            if "STRICT_TRANS_TABLES" in mode:
                with pytest.raises(DataError) as error:
                    connection.execute(text(f"INSERT INTO `{name}` (amount) VALUES (100000000.00)"))
                assert error.value.orig.args[0] == 1264
                connection.rollback()
            else:
                connection.execute(text(f"INSERT INTO `{name}` (amount) VALUES (100000000.00)"))
                warnings = connection.execute(text("SHOW WARNINGS")).all()
                assert any(row[1] == 1264 for row in warnings)
                assert connection.execute(text(f"SELECT amount FROM `{name}`")).scalar_one() == Decimal("99999999.99")
                connection.rollback()
            zero_date = text(f"INSERT INTO `{name}` (day) VALUES ('0000-00-00')")
            if "NO_ZERO_DATE" in mode:
                with pytest.raises(OperationalError) as error:
                    connection.execute(zero_date)
                assert error.value.orig.args[0] == 1292
            else:
                connection.execute(zero_date)
                assert connection.execute(text(f"SELECT CAST(day AS CHAR) FROM `{name}`")).scalar_one() == "0000-00-00"
            connection.rollback()
            assert settings(connection)[2:] == observed[2:]
        mysql57.evidence.setdefault("utc_sql_modes", []).append(mode)
    finally:
        configured.dispose()


@pytest.mark.parametrize("offset", [-7, 5.5])
def test_historical_legacy_timestamp_instants_are_preserved_not_rewritten(mysql57, engine, app, offset):
    legacy = make_stay(engine)
    with Session(engine) as db:
        cancellation = app.booking_service.cancel_booking(db, legacy["reservation"], legacy["owner"])
        cancellation_id = cancellation.cancellation_payment_id
    wall = datetime(2020, 1, 1, 12)
    zone = "-07:00" if offset == -7 else "+05:30"
    targets = [("users", "user_id", legacy["owner"]),
               ("reservations", "reservation_id", legacy["reservation"]),
               ("payments", "payment_id", legacy["payment"]),
               ("payments", "payment_id", cancellation_id)]
    with mysql57.connect(mysql57.upgrade) as old_connection:
        with old_connection.cursor() as cursor:
            cursor.execute("SET SESSION time_zone=%s", (zone,))
            for table, key, identity in targets:
                cursor.execute(f"UPDATE {table} SET created_at=%s WHERE {key}=%s", (wall, identity))
        old_connection.commit()
        with old_connection.cursor() as cursor:
            epochs_before = []
            for table, key, identity in targets:
                cursor.execute(f"SELECT UNIX_TIMESTAMP(created_at) FROM {table} WHERE {key}=%s", (identity,))
                epochs_before.append(cursor.fetchone()[0])
    expected = wall - timedelta(hours=offset)
    with Session(engine) as db:
        for model, identity in ((app.User, legacy["owner"]), (app.Reservation, legacy["reservation"]),
                                (app.Payment, legacy["payment"]), (app.Payment, cancellation_id)):
            value = db.get(model, identity).created_at
            assert value == expected and value.tzinfo is None
            assert value.replace(tzinfo=timezone.utc).isoformat().endswith("+00:00")
        # Pure financial reads do not change any historical timestamp.
        app.reservation_change_payment_service.get_reservation_financial_summary(db, legacy["reservation"], legacy["owner"])
    with engine.connect() as connection:
        epochs_after = [connection.execute(text(
            f"SELECT UNIX_TIMESTAMP(created_at) FROM {table} WHERE {key}=:identity"
        ), {"identity": identity}).scalar_one() for table, key, identity in targets]
    assert epochs_before == epochs_after
    mysql57.evidence["legacy_timestamp_compatibility"] = "known non-UTC sessions: instants preserved; UTC display changes"


def test_future_legacy_and_cancellation_defaults_use_utc_under_non_utc_host_clock(engine, app, monkeypatch):
    from app.utilities import timestamps
    instant = datetime(2026, 10, 10, 12, 34, 56, 123456, tzinfo=timezone.utc)

    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None) - timedelta(hours=7)

    monkeypatch.setattr(timestamps, "datetime", HostClock)
    with Session(engine) as db:
        user = app.User(email=f"{uuid4()}@example.test", password_hash="synthetic-only")
        db.add(user)
        db.flush()
        reservation = app.Reservation(user_id=user.user_id, room_type_id=7201,
                                      check_in_date=datetime(2030, 11, 1).date(),
                                      check_out_date=datetime(2030, 11, 3).date(), total_price=210, status="confirmed")
        db.add(reservation)
        db.flush()
        payment = app.Payment(reservation_id=reservation.reservation_id, amount=226.8,
                              payment_type="booking", payment_status="paid")
        db.add(payment)
        db.commit()
        expected = instant.replace(tzinfo=None, microsecond=0)  # Legacy SQL TIMESTAMP has second precision.
        for row in (user, reservation, payment):
            db.refresh(row)
            assert row.created_at == expected
        result = app.booking_service.cancel_booking(db, reservation.reservation_id, user.user_id)
        cancellation = db.get(app.Payment, result.cancellation_payment_id)
        assert cancellation.created_at == expected
        for row in (user, reservation, payment):
            db.refresh(row)
            assert row.created_at == expected


@pytest.mark.parametrize("offset", [-7, 5.5])
def test_quote_expiration_uses_aware_utc_even_for_non_utc_caller_clock(engine, app, stay, provider, offset):
    from app.utilities import reservation_change_quote
    request = review(engine, app, stay)
    claims = reservation_change_quote.decode_change_quote_claims(request.quote_id)
    assert claims.exp - claims.iat == 600
    expired = datetime.fromtimestamp(claims.exp, timezone.utc).astimezone(timezone(timedelta(hours=offset)))
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            app.reservation_change_service.confirm_reservation_change(
                db, request, stay["reservation"], stay["owner"], now=expired,
            )
        assert error.value.status_code == 409
        assert db.get(app.Reservation, stay["reservation"]).revision == 0
        assert app.booking_dao.get_reservation_change_history(db, stay["reservation"]) == []
    assert provider["calls"] == 1


def test_change_event_defaults_and_settlement_roundtrip_are_utc(engine, app, stay, provider, mysql57):
    from app.schemas.reservation_change_payment_schema import AdjustmentSettlementRequest
    from app.utilities import reservation_change_quote
    provider["nightly"] = 120
    request = review(engine, app, stay)
    claims = reservation_change_quote.decode_change_quote_claims(request.quote_id)
    with engine.connect() as connection:
        before = connection.execute(text("SELECT UTC_TIMESTAMP(6)")).scalar_one()
    with Session(engine) as db:
        receipt = app.reservation_change_service.confirm_reservation_change(db, request, stay["reservation"], stay["owner"])
        change = db.get(app.ReservationChangeEvent, receipt["change_id"])
        adjustment = db.get(app.ReservationChangeAdjustment, receipt["adjustment"]["adjustment_id"])
        after = db.execute(text("SELECT UTC_TIMESTAMP(6)")).scalar_one()
        assert change.quote_issued_at == datetime.fromtimestamp(claims.iat, timezone.utc).replace(tzinfo=None)
        assert change.quote_expires_at == change.quote_issued_at + timedelta(minutes=10)
        assert before <= change.created_at <= after
        assert before <= adjustment.created_at <= after
        assert before <= adjustment.updated_at <= after
        instant = datetime.fromtimestamp(claims.iat, timezone.utc).replace(microsecond=123456) + timedelta(seconds=45)
        result = app.reservation_change_payment_service.settle_reservation_change_charge(
            db, AdjustmentSettlementRequest(accepted_amount="45.36", reservation_revision=1, accept_payment=True),
            adjustment.adjustment_id, stay["owner"], now=instant.astimezone(timezone(timedelta(hours=5.5))),
        )
        db.refresh(adjustment)
        assert adjustment.settled_at == adjustment.updated_at == instant.replace(tzinfo=None)
        assert result.settled_at == instant and result.settled_at.tzinfo == timezone.utc
        assert result.model_dump(mode="json")["settled_at"] == instant.isoformat().replace("+00:00", "Z")
        summary = app.reservation_change_payment_service.get_reservation_financial_summary(db, stay["reservation"], stay["owner"])
        assert summary.adjustments[0].settled_at == instant
        mysql57.evidence["utc_settlement"] = {"datetime6_roundtrip": True, "aware_utc_serialization": True}


def test_flushed_settlement_timestamps_and_revision_roll_back(engine, app, stay, provider, monkeypatch):
    from app.schemas.reservation_change_payment_schema import AdjustmentSettlementRequest
    provider["nightly"] = 120
    with Session(engine) as db:
        receipt = app.reservation_change_service.confirm_reservation_change(
            db, review(engine, app, stay), stay["reservation"], stay["owner"],
        )
        identity = receipt["adjustment"]["adjustment_id"]
        baseline = db.get(app.ReservationChangeAdjustment, identity).updated_at

        def fail_commit():
            db.flush()
            raise SQLAlchemyError("Synthetic commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(HTTPException) as error:
            app.reservation_change_payment_service.settle_reservation_change_charge(
                db, AdjustmentSettlementRequest(accepted_amount="45.36", reservation_revision=1, accept_payment=True),
                identity, stay["owner"],
            )
        assert error.value.status_code == 500
    with Session(engine) as db:
        row = db.get(app.ReservationChangeAdjustment, identity)
        assert row.status == "pending" and row.settled_at is None and row.updated_at == baseline
        assert db.get(app.Reservation, stay["reservation"]).revision == 1


def test_no_probe_tables_or_mutated_session_state_leak_between_tests(mysql57, utc_engine):
    with utc_engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() "
            "AND table_name LIKE 'us72\\_utc\\_probe\\_%'"
        )).scalar_one() == 0
        assert settings(connection)[1] == "+00:00"
        assert "STRICT_TRANS_TABLES" in settings(connection)[3]
    mysql57.evidence["utc_no_cross_test_contamination"] = True
