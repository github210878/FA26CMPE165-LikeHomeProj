"""Live MySQL tests, skipped unless the Docker-owned runner supplies context.

No environment variable or application DB URL can opt this module into a live
connection. App imports are deferred until the runner's isolation gate passes.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from threading import Barrier, Event
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def mysql57(request):
    context = getattr(request.config, "_us72_disposable", None)
    if context is None:
        pytest.skip("Use run_mysql57_verification.py --disposable; application DB configuration is forbidden")
    return context


@pytest.fixture(scope="session")
def engine(mysql57):
    return mysql57.engine(mysql57.upgrade)


@pytest.fixture(scope="session", params=["upgrade", "fresh"])
def contract_engine(mysql57, request):
    return mysql57.engine(getattr(mysql57, request.param))


@pytest.fixture(scope="session")
def app(mysql57):
    from app.config.database import Base
    from app.models import (Hotel, Payment, Reservation, ReservationChangeAdjustment,
                            ReservationChangeEvent, RoomType, User)
    from app.repositories import booking_dao
    from app.services import booking_service, hotel_service, reservation_change_service
    from app.services import reservation_change_payment_service
    from app.utilities import serpapi_client
    return SimpleNamespace(**locals())


def make_stay(engine, *, status="paid", owner=None, check_in=date(2030, 11, 1)):
    with engine.begin() as connection:
        if owner is None:
            owner = connection.execute(text(
                "INSERT INTO users(email,password_hash,full_name) VALUES(:email,'synthetic-only','Synthetic Owner')"
            ), {"email": f"{uuid4()}@example.test"}).lastrowid
        reservation = connection.execute(text(
            "INSERT INTO reservations(user_id,room_type_id,check_in_date,check_out_date,total_price) "
            "VALUES(:owner,7201,:start,:end,210.00)"
        ), {"owner": owner, "start": check_in, "end": check_in + timedelta(days=2)}).lastrowid
        payment = connection.execute(text(
            "INSERT INTO payments(reservation_id,amount,payment_type,payment_status) "
            "VALUES(:reservation,226.80,'booking',:status)"
        ), {"reservation": reservation, "status": status}).lastrowid
    return dict(owner=owner, reservation=reservation, payment=payment, start=check_in)


@pytest.fixture
def stay(engine):
    return make_stay(engine)


def event_values(stay, **overrides):
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=123456)
    values = dict(
        reservation_id=stay["reservation"], user_id=stay["owner"], booking_payment_id=stay["payment"],
        quote_jti=str(uuid4()), quote_sha256=b"q" * 32, request_sha256=b"r" * 32,
        original_state_sha256=b"s" * 32, revision_before=0, revision_after=1,
        old_room_type_id=7201, new_room_type_id=7202,
        old_check_in_date=stay["start"], old_check_out_date=stay["start"] + timedelta(days=2),
        new_check_in_date=stay["start"] + timedelta(days=3), new_check_out_date=stay["start"] + timedelta(days=5),
        old_reservation_total=Decimal("210.00"), new_reservation_total=Decimal("250.00"),
        old_payment_obligation=Decimal("226.80"), new_payment_obligation=Decimal("270.00"),
        booking_payment_status_before="paid", context_json={"q": "Synthetic City", "adults": 2, "children": 0},
        fresh_quote_json={"likehome_payment_amount": "270.00"}, response_json={"applied_revision": 1},
        quote_issued_at=now, quote_expires_at=now + timedelta(minutes=10),
    )
    return values | overrides


def insert_event(db, app, stay, **overrides):
    record = app.ReservationChangeEvent(**event_values(stay, **overrides))
    db.add(record)
    db.flush()
    return record


def insert_adjustment(db, app, change_id, **overrides):
    row = app.ReservationChangeAdjustment(**(
        dict(change_id=change_id, amount=Decimal("43.20"), kind="charge", status="pending") | overrides
    ))
    db.add(row)
    db.flush()
    return row


def reject_insert(db, code, operation, key=None):
    with pytest.raises(IntegrityError) as failure, db.begin_nested():
        operation()
    assert failure.value.orig.args[0] == code
    if key:
        assert key in str(failure.value.orig)


@pytest.mark.parametrize("schema_kind", ["upgrade", "fresh"])
def test_live_schema_metadata(mysql57, schema_kind, app):
    schema = getattr(mysql57, schema_kind)
    engine = mysql57.engine(schema)
    inspector = inspect(engine)
    revision = next(c for c in inspector.get_columns("reservations") if c["name"] == "revision")
    assert revision["type"].unsigned and not revision["nullable"]
    # SQLAlchemy reflection quotes this numeric server default on MySQL 5.7.
    assert revision["default"] in ("0", "'0'")
    reservation_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("reservations")}
    assert reservation_indexes["ix_reservations_user_dates"] == ["user_id", "check_in_date", "check_out_date"]
    expected_uniques = {
        "reservation_change_events": {
            "uq_change_quote_jti": ["quote_jti"],
            "uq_change_reservation_revision": ["reservation_id", "revision_after"],
        },
        "reservation_change_adjustments": {
            "uq_adjustment_change_role": ["change_id", "entry_role"],
            "uq_adjustment_reconciliation": ["reconciles_adjustment_id"],
            "uq_adjustment_id_change": ["adjustment_id", "change_id"],
        },
    }
    for table, keys in expected_uniques.items():
        assert inspector.get_table_options(table)["mysql_engine"] == "InnoDB"
        assert {k["name"]: k["column_names"] for k in inspector.get_unique_constraints(table)} == keys
        for column in inspector.get_columns(table):
            if column["name"] in ("amount", "old_reservation_total", "new_reservation_total",
                                   "old_payment_obligation", "new_payment_obligation"):
                assert (column["type"].precision, column["type"].scale) == (10, 2)
            if column["name"].endswith("_at"):
                assert column["type"].fsp == 6
    event_fks = {f["name"]: f for f in inspector.get_foreign_keys("reservation_change_events")}
    assert set(event_fks) == {"fk_change_reservation", "fk_change_user", "fk_change_payment",
                              "fk_change_old_room", "fk_change_new_room"}
    # SHOW CREATE can omit RESTRICT (the default); information_schema below
    # compares the actual rules and full FK targets across both installations.
    assert all(f["options"].get("ondelete", "RESTRICT") == "RESTRICT" and
               f["options"].get("onupdate", "RESTRICT") == "CASCADE" for f in event_fks.values())
    adjustment_fks = {f["name"]: f for f in inspector.get_foreign_keys("reservation_change_adjustments")}
    assert set(adjustment_fks) == {"fk_adjustment_change", "fk_adjustment_reconciles"}
    assert all(f["options"].get("ondelete", "RESTRICT") == "RESTRICT" and
               f["options"].get("onupdate", "RESTRICT") == "RESTRICT" for f in adjustment_fks.values())
    assert adjustment_fks["fk_adjustment_reconciles"]["constrained_columns"] == ["reconciles_adjustment_id", "change_id"]
    assert adjustment_fks["fk_adjustment_reconciles"]["referred_columns"] == ["adjustment_id", "change_id"]
    for table, field in [("reservations", "total_price"), ("payments", "amount"), ("room_types", "price_per_night")]:
        assert inspector.get_table_options(table)["mysql_engine"] == "InnoDB"
        money = next(c["type"] for c in inspector.get_columns(table) if c["name"] == field)
        assert (money.precision, money.scale) == (10, 2)
    for model in (app.ReservationChangeEvent, app.ReservationChangeAdjustment):
        columns = {c["name"]: c for c in inspector.get_columns(model.__tablename__)}
        assert set(columns) == set(model.__table__.columns.keys())
        assert all(columns[c.name]["nullable"] == c.nullable for c in model.__table__.columns)
    with mysql57.connect(schema) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COLUMN_TYPE,CHARACTER_SET_NAME,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='reservation_change_events' AND COLUMN_NAME='quote_jti'", (schema,))
        assert cursor.fetchone() == ("char(36)", "ascii", "ascii_bin")
        cursor.execute("SELECT COLUMN_NAME,DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='reservation_change_events' AND COLUMN_NAME LIKE '%%json' ORDER BY COLUMN_NAME", (schema,))
        assert cursor.fetchall() == (("context_json", "json"), ("fresh_quote_json", "json"), ("response_json", "json"))


def test_fresh_and_upgrade_full_metadata_match(mysql57):
    definitions = {}
    for schema in (mysql57.upgrade, mysql57.fresh):
        with mysql57.connect(schema) as connection, connection.cursor() as cursor:
            metadata = {}
            queries = {
                "tables": "SELECT TABLE_NAME,ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
                "columns": "SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,CHARACTER_SET_NAME,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,COLUMN_NAME",
                "indexes": "SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX",
                "foreign_keys": "SELECT k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION,k.COLUMN_NAME,k.REFERENCED_TABLE_NAME,k.REFERENCED_COLUMN_NAME,r.UPDATE_RULE,r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.TABLE_SCHEMA=%s ORDER BY k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION",
            }
            for key, query in queries.items():
                cursor.execute(query, (schema,))
                metadata[key] = cursor.fetchall()
            cursor.execute("SELECT COLUMN_NAME,ORDINAL_POSITION FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='reservations' ORDER BY ORDINAL_POSITION", (schema,))
            mysql57.evidence[f"{schema.split('_')[1]}_reservation_column_order"] = cursor.fetchall()
            definitions[schema] = metadata
    assert definitions[mysql57.upgrade] == definitions[mysql57.fresh]
    mysql57.evidence["schema_metadata"] = definitions[mysql57.upgrade]
    mysql57.evidence["schema_differences"] = ["reservations column ordinal positions: revision appended on upgrade, before guest fields on fresh install"]


def test_load_historical_records_and_model_registration(engine, app):
    assert app.Base.metadata.tables["reservation_change_events"] is app.ReservationChangeEvent.__table__
    assert app.Base.metadata.tables["reservation_change_adjustments"] is app.ReservationChangeAdjustment.__table__
    with Session(engine) as db:
        for reservation_id, payment_id, status in [(7301, 7401, "pending"), (7302, 7402, "paid")]:
            reservation = db.get(app.Reservation, reservation_id)
            payment = db.get(app.Payment, payment_id)
            assert reservation.revision == 0 and reservation.total_price == 210.02
            assert payment.amount == 226.82 and payment.payment_status == status
            assert app.booking_dao.get_reservation_change_history(db, reservation_id) == []
            assert app.booking_dao.get_adjustments_for_change(db, reservation_id) == []


@pytest.mark.parametrize("duplicate", ["quote", "revision"])
def test_actual_event_unique_inserts(contract_engine, app, duplicate):
    stay = make_stay(contract_engine)
    with Session(contract_engine) as db:
        first = insert_event(db, app, stay)
        overrides = dict(quote_jti=first.quote_jti, revision_after=2) if duplicate == "quote" else {}
        key = "uq_change_quote_jti" if duplicate == "quote" else "uq_change_reservation_revision"
        reject_insert(db, 1062, lambda: insert_event(db, app, stay, **overrides), key)
        db.rollback()


@pytest.mark.parametrize("field", ["reservation_id", "user_id", "booking_payment_id", "old_room_type_id", "new_room_type_id"])
def test_actual_event_foreign_key_inserts(contract_engine, app, field):
    stay = make_stay(contract_engine)
    with Session(contract_engine) as db:
        reject_insert(db, 1452, lambda: insert_event(db, app, stay, **{field: 2147483647}))
        db.rollback()


def test_adjustment_uniques_cross_change_fk_and_history_restriction(contract_engine, app):
    stay = make_stay(contract_engine)
    with Session(contract_engine) as db:
        first = insert_event(db, app, stay)
        second = insert_event(db, app, stay, revision_before=1, revision_after=2)
        primary = insert_adjustment(db, app, first.change_id, status="paid", settled_at=datetime.now())
        reject_insert(db, 1062, lambda: insert_adjustment(db, app, first.change_id), "uq_adjustment_change_role")
        reject_insert(db, 1452, lambda: insert_adjustment(db, app, 2147483647), "fk_adjustment_change")
        reject_insert(db, 1452, lambda: insert_adjustment(
            db, app, second.change_id, entry_role="cancellation_reconciliation",
            reconciles_adjustment_id=primary.adjustment_id, kind="credit", status="recorded",
        ), "fk_adjustment_reconciles")
        reversal = insert_adjustment(db, app, first.change_id, entry_role="cancellation_reconciliation",
                                     reconciles_adjustment_id=primary.adjustment_id, kind="credit", status="recorded")
        reject_insert(db, 1062, lambda: insert_adjustment(
            db, app, second.change_id, entry_role="cancellation_reconciliation",
            reconciles_adjustment_id=primary.adjustment_id, kind="credit", status="recorded",
        ), "uq_adjustment_reconciliation")
        assert reversal.amount == primary.amount == Decimal("43.20")
        for table, key, value in [("reservation_change_events", "change_id", first.change_id),
                                   ("reservation_change_adjustments", "adjustment_id", primary.adjustment_id),
                                   ("reservations", "reservation_id", stay["reservation"]),
                                   ("payments", "payment_id", stay["payment"]),
                                   ("users", "user_id", stay["owner"]),
                                   ("room_types", "room_type_id", 7201)]:
            reject_insert(db, 1451, lambda: db.execute(text(f"DELETE FROM {table} WHERE {key}=:id"), {"id": value}))
        db.rollback()


def test_json_microseconds_and_ignored_check_constraints(engine, app, stay):
    with Session(engine) as db:
        record = insert_event(db, app, stay)
        record_id = record.change_id
        expected_time = record.quote_issued_at
        db.commit()
        db.expire_all()
        record = db.get(app.ReservationChangeEvent, record_id)
        assert record.quote_issued_at == expected_time and record.quote_issued_at.microsecond == 123456
        assert record.context_json["adults"] == 2
        assert db.execute(text("SELECT JSON_UNQUOTE(JSON_EXTRACT(fresh_quote_json,'$.likehome_payment_amount')) FROM reservation_change_events WHERE change_id=:id"), {"id": record_id}).scalar_one() == "270.00"
        with pytest.raises(OperationalError) as invalid, db.begin_nested():
            db.execute(text("UPDATE reservation_change_events SET context_json='invalid json' WHERE change_id=:id"), {"id": record_id})
        assert invalid.value.orig.args[0] == 3140
        # Deliberate invalid business values are rolled back: do not claim the DB
        # enforces policies which are guarded by input schemas/services instead.
        with db.begin_nested() as nested:
            negative = insert_adjustment(db, app, record_id, amount=Decimal("-0.01"))
            assert negative.amount == Decimal("-0.01")
            db.execute(text("UPDATE reservations SET check_out_date=check_in_date WHERE reservation_id=:id"), {"id": stay["reservation"]})
            nested.rollback()
        db.rollback()


@pytest.mark.parametrize("amount", ["0.01", "0.10", "226.82", "99999999.99"])
def test_exact_mysql_decimal_and_legacy_cent_roundtrips(engine, app, stay, amount):
    from app.utilities.reservation_change_serialization import canonical_money
    value = Decimal(amount)
    with Session(engine) as db:
        record = insert_event(db, app, stay, new_payment_obligation=value, new_reservation_total=value)
        adjustment = insert_adjustment(db, app, record.change_id, amount=value)
        db.get(app.Reservation, stay["reservation"]).total_price = float(value)
        db.get(app.Payment, stay["payment"]).amount = float(value)
        db.commit()
        db.expire_all()
        assert db.get(app.ReservationChangeEvent, record.change_id).new_payment_obligation == value
        assert isinstance(db.get(app.ReservationChangeEvent, record.change_id).new_payment_obligation, Decimal)
        assert db.get(app.ReservationChangeAdjustment, adjustment.adjustment_id).amount == value
        assert canonical_money(db.get(app.Reservation, stay["reservation"]).total_price) == amount
        assert canonical_money(db.get(app.Payment, stay["payment"]).amount) == amount
        owned = app.booking_dao.get_owned_change_adjustment(db, adjustment.adjustment_id, stay["owner"])
        assert owned is not None and owned[1].booking_payment_id == stay["payment"]
        assert app.booking_dao.get_owned_change_adjustment(db, adjustment.adjustment_id, 7001) is None


def wait_for_innodb_wait(mysql57, connection_id, future):
    deadline = time.monotonic() + 6
    with mysql57.connect(mysql57.upgrade) as observer, observer.cursor() as cursor:
        while time.monotonic() < deadline:
            cursor.execute("SELECT COUNT(*) FROM information_schema.INNODB_LOCK_WAITS w JOIN information_schema.INNODB_TRX t ON t.trx_id=w.requesting_trx_id WHERE t.trx_mysql_thread_id=%s", (connection_id,))
            if cursor.fetchone()[0]:
                assert not future.done()
                return
            if future.done():
                future.result()  # Show any actual worker error.
                pytest.fail("Competing transaction did not wait on an InnoDB lock")
            time.sleep(0.02)
    pytest.fail("No InnoDB wait observed within the bounded test interval")


@pytest.mark.parametrize("release", ["commit", "rollback"])
@pytest.mark.parametrize("table", ["users", "reservations", "payments", "reservation_change_adjustments"])
def test_real_row_lock_wait_and_release(mysql57, engine, app, stay, table, release):
    row_keys = {"users": ("user_id", stay["owner"], "reward_points"),
                "reservations": ("reservation_id", stay["reservation"], "revision"),
                "payments": ("payment_id", stay["payment"], "amount")}
    if table == "reservation_change_adjustments":
        with Session(engine) as db:
            record = insert_event(db, app, stay)
            adjustment = insert_adjustment(db, app, record.change_id)
            adjustment_id = adjustment.adjustment_id
            db.commit()
        row_keys[table] = ("adjustment_id", adjustment_id, "amount")
    key, row_id, field = row_keys[table]
    started = Event()
    worker_ids = []

    def waiter():
        with mysql57.connect(mysql57.upgrade) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT CONNECTION_ID()")
            worker_ids.append(cursor.fetchone()[0])
            started.set()
            cursor.execute(f"SELECT {field} FROM {table} WHERE {key}=%s FOR UPDATE", (row_id,))
            value = cursor.fetchone()[0]
            connection.commit()
            return value

    with mysql57.connect(mysql57.upgrade) as holder, holder.cursor() as cursor:
        cursor.execute(f"SELECT {field} FROM {table} WHERE {key}=%s FOR UPDATE", (row_id,))
        original = cursor.fetchone()[0]
        cursor.execute(f"UPDATE {table} SET {field}={field}+1 WHERE {key}=%s", (row_id,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(waiter)
            try:
                assert started.wait(3)
                wait_for_innodb_wait(mysql57, worker_ids[0], future)
            finally:
                getattr(holder, release)()
            assert future.result(timeout=10) == original + (1 if release == "commit" else 0)
    mysql57.evidence.setdefault("observed_row_lock_waits", []).append(f"{table}: {release}")


def test_repeatable_read_snapshot_is_replaced_after_rollback(engine, app, stay):
    with Session(engine) as reader, Session(engine) as writer:
        assert reader.get(app.Reservation, stay["reservation"]).revision == 0
        writer.get(app.Reservation, stay["reservation"]).revision = 1
        writer.commit()
        reader.expire_all()
        assert reader.get(app.Reservation, stay["reservation"]).revision == 0  # Actual RR snapshot.
        reader.rollback()
        assert app.booking_dao.lock_user_for_booking(reader, stay["owner"])
        assert app.booking_dao.lock_reservation_for_change(reader, stay["reservation"], stay["owner"]).revision == 1
        assert reader.execute(text("SELECT revision FROM reservations WHERE reservation_id=:id"), {"id": stay["reservation"]}).scalar_one() == 1
        reader.rollback()


def test_duplicate_quote_sql_race_rolls_back_candidate(mysql57, engine, app, stay):
    other = make_stay(engine)
    values = event_values(stay)
    started = Event()
    worker_ids = []
    columns = list(values)
    # JSON is encoded explicitly because these INSERTs exercise SQL constraints.
    parameters = tuple(json.dumps(values[c]) if c.endswith("_json") else values[c] for c in columns)
    sql = f"INSERT INTO reservation_change_events ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})"

    def duplicate():
        with mysql57.connect(mysql57.upgrade) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE reservations SET total_price=999.99 WHERE reservation_id=%s", (other["reservation"],))
            cursor.execute("SELECT CONNECTION_ID()")
            worker_ids.append(cursor.fetchone()[0])
            changed = values | {"reservation_id": other["reservation"], "user_id": other["owner"], "booking_payment_id": other["payment"]}
            candidate = tuple(json.dumps(changed[c]) if c.endswith("_json") else changed[c] for c in columns)
            started.set()
            try:
                cursor.execute(sql, candidate)
            except Exception as exc:
                connection.rollback()
                assert exc.args[0] == 1062 and "uq_change_quote_jti" in str(exc)
                return "duplicate rejected"
            pytest.fail("Duplicate quote committed")

    with mysql57.connect(mysql57.upgrade) as holder, holder.cursor() as cursor:
        cursor.execute(sql, parameters)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(duplicate)
            try:
                assert started.wait(3)
                wait_for_innodb_wait(mysql57, worker_ids[0], future)
            finally:
                holder.commit()
            assert future.result(timeout=10) == "duplicate rejected"
    with Session(engine) as db:
        assert db.get(app.Reservation, other["reservation"]).total_price == 210.00
        assert db.execute(text("SELECT COUNT(*) FROM reservation_change_events WHERE quote_jti=:jti"), {"jti": values["quote_jti"]}).scalar_one() == 1
        assert app.booking_dao.get_reservation_change_history(db, other["reservation"]) == []


@pytest.fixture
def provider(app, monkeypatch):
    state = {"nightly": 80, "calls": 0}

    def synthetic(params):
        state["calls"] += 1
        nights = (date.fromisoformat(params["check_out_date"]) - date.fromisoformat(params["check_in_date"])).days
        nightly = state["nightly"]
        return {"name": "Disposable Hotel", "property_token": params["property_token"], "prices": [{
            "source": "Synthetic provider", "num_guests": 2,
            "rate_per_night": {"extracted_before_taxes_fees": nightly},
            "total_rate": {"extracted_before_taxes_fees": nightly * nights, "extracted_lowest": nightly * nights},
        }]}

    monkeypatch.setattr(app.serpapi_client, "search_google_hotels", synthetic)
    return state


def review(engine, app, stay, *, start=date(2030, 11, 4)):
    from app.schemas.reservation_change_schema import ReservationChangeReviewRequest, ReservationChangeConfirmRequest
    with Session(engine) as db:
        reviewed = app.reservation_change_service.quote_reservation_change(db, ReservationChangeReviewRequest(
            check_in_date=start, check_out_date=start + timedelta(days=2), q="Synthetic City", adults=2, children=0,
        ), stay["reservation"], stay["owner"])
    return ReservationChangeConfirmRequest(
        check_in_date=reviewed.quote.check_in_date, check_out_date=reviewed.quote.check_out_date,
        quote_id=reviewed.quote_id, accept_quote=True, price_per_night=reviewed.quote.current_price_per_night,
        accepted_payment_amount=reviewed.quote.likehome_payment_amount,
    )


def confirm(engine, app, stay, request):
    with Session(engine) as db:
        return app.reservation_change_service.confirm_reservation_change(db, request, stay["reservation"], stay["owner"])


def race_attempt(operation):
    from fastapi import HTTPException
    try:
        return operation()
    except HTTPException as exc:
        assert exc.status_code == 409, f"Unexpected service failure: {exc.status_code}: {exc.detail}"
        return 409


@pytest.mark.parametrize("status", ["pending", "paid"])
@pytest.mark.parametrize("same_quote", [True, False])
def test_real_confirmation_race(engine, app, provider, monkeypatch, status, same_quote):
    stay = make_stay(engine, status=status)
    first = review(engine, app, stay)
    second = first if same_quote else review(engine, app, stay, start=date(2030, 11, 8))
    barrier = Barrier(2)
    original = app.hotel_service.revalidate_hotel

    def synchronize(context):
        response = original(context)
        barrier.wait(timeout=8)
        return response

    monkeypatch.setattr(app.hotel_service, "revalidate_hotel", synchronize)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(race_attempt, lambda request=request: confirm(engine, app, stay, request)) for request in (first, second)]
        results = [f.result(timeout=15) for f in futures]
    if same_quote:
        assert results[0] == results[1] and isinstance(results[0], dict)
    else:
        assert sum(isinstance(r, dict) for r in results) == 1 and 409 in results
    with Session(engine) as db:
        assert db.get(app.Reservation, stay["reservation"]).revision == 1
        assert len(app.booking_dao.get_reservation_change_history(db, stay["reservation"])) == 1
        assert len(app.booking_dao.get_adjustments_for_change(db, stay["reservation"])) == (1 if status == "paid" else 0)
        assert db.get(app.Payment, stay["payment"]).amount == (226.8 if status == "paid" else 181.44)


def test_same_user_different_stays_cannot_both_commit_overlap(engine, app, provider, monkeypatch):
    first = make_stay(engine, status="pending")
    second = make_stay(engine, status="pending", owner=first["owner"], check_in=date(2030, 12, 1))
    requests = [review(engine, app, stay) for stay in (first, second)]
    barrier = Barrier(2)
    original = app.hotel_service.revalidate_hotel

    def synchronize(context):
        result = original(context)
        barrier.wait(timeout=8)
        return result

    monkeypatch.setattr(app.hotel_service, "revalidate_hotel", synchronize)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(race_attempt, lambda stay=stay, request=request: confirm(engine, app, stay, request))
                   for stay, request in zip((first, second), requests)]
        results = [f.result(timeout=15) for f in futures]
    assert sum(isinstance(r, dict) for r in results) == 1 and 409 in results
    with Session(engine) as db:
        assert sum(db.get(app.Reservation, s["reservation"]).revision for s in (first, second)) == 1
        assert sum(len(app.booking_dao.get_reservation_change_history(db, s["reservation"])) for s in (first, second)) == 1


def test_service_failure_rolls_back_flushed_reservation_event_room_and_adjustment(engine, app, stay, provider, monkeypatch):
    from fastapi import HTTPException
    request = review(engine, app, stay)
    with Session(engine) as db:
        rooms = db.execute(text("SELECT * FROM room_types ORDER BY room_type_id")).all()
    original = app.booking_dao.stage_booking_record

    def fail_after_flush(db, record):
        result = original(db, record)
        if isinstance(record, app.ReservationChangeAdjustment):
            raise RuntimeError("Synthetic failure after actual ledger flush")
        return result

    monkeypatch.setattr(app.booking_dao, "stage_booking_record", fail_after_flush)
    with pytest.raises(HTTPException) as failure:
        confirm(engine, app, stay, request)
    assert failure.value.status_code == 500
    with Session(engine) as db:
        reservation = db.get(app.Reservation, stay["reservation"])
        assert reservation.revision == 0 and reservation.total_price == 210.00 and reservation.room_type_id == 7201
        assert reservation.check_in_date == stay["start"]
        assert db.get(app.Payment, stay["payment"]).amount == 226.80
        assert app.booking_dao.get_reservation_change_history(db, stay["reservation"]) == []
        assert app.booking_dao.get_adjustments_for_change(db, stay["reservation"]) == []
        assert db.execute(text("SELECT * FROM room_types ORDER BY room_type_id")).all() == rooms


def row_snapshot(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def test_two_change_financial_ledger_settlement_and_cancellation(engine, app, stay, provider, mysql57):
    from app.schemas.reservation_change_payment_schema import AdjustmentSettlementRequest
    provider["nightly"] = 120
    first = confirm(engine, app, stay, review(engine, app, stay))
    assert first["payment_difference"] == "45.36"
    adjustment_id = first["adjustment"]["adjustment_id"]
    with Session(engine) as db:
        settled = app.reservation_change_payment_service.settle_reservation_change_charge(
            db, AdjustmentSettlementRequest(accepted_amount="45.36", reservation_revision=1, accept_payment=True),
            adjustment_id, stay["owner"],
        )
        assert settled.status == "paid"
        original_charge = row_snapshot(db.get(app.ReservationChangeAdjustment, adjustment_id))
        retry = app.reservation_change_payment_service.settle_reservation_change_charge(
            db, AdjustmentSettlementRequest(accepted_amount="45.36", reservation_revision=0, accept_payment=True),
            adjustment_id, stay["owner"],
        )
        assert retry == settled
    provider["nightly"] = 90
    second = confirm(engine, app, stay, review(engine, app, stay, start=date(2030, 11, 8)))
    assert second["revision"] == 3 and second["payment_difference"] == "-68.04"
    with Session(engine) as db:
        events_before = [row_snapshot(r) for r in app.booking_dao.get_reservation_change_history(db, stay["reservation"])]
        credit_id = second["adjustment"]["adjustment_id"]
        original_credit = row_snapshot(db.get(app.ReservationChangeAdjustment, credit_id))
        calls_before = provider["calls"]
        cancelled = app.booking_service.cancel_booking(db, stay["reservation"], stay["owner"])
        assert cancelled.cancellation_amount == 37.8
        assert provider["calls"] == calls_before
        summary = app.reservation_change_payment_service.get_reservation_financial_summary(db, stay["reservation"], stay["owner"])
        assert summary.reservation_revision == 4 and summary.reservation_status == "cancelled"
        assert summary.paid_additional_charges == 45.36 and summary.recorded_internal_credits == 68.04
        assert summary.reconciliation_credits == 45.36 and summary.reconciliation_debits == 68.04
        assert summary.outstanding_additional_amount == 0 and summary.outstanding_cancellation_amount == 37.8
        assert db.get(app.Payment, stay["payment"]).amount == 226.80
        assert db.get(app.Payment, stay["payment"]).payment_status == "refunded"
        assert events_before == [row_snapshot(r) for r in app.booking_dao.get_reservation_change_history(db, stay["reservation"])]
        assert original_charge == row_snapshot(db.get(app.ReservationChangeAdjustment, adjustment_id))
        assert original_credit == row_snapshot(db.get(app.ReservationChangeAdjustment, credit_id))
        for primary_id, amount, kind in [(adjustment_id, "45.36", "credit"), (credit_id, "68.04", "charge")]:
            reversals = db.scalars(select(app.ReservationChangeAdjustment).where(app.ReservationChangeAdjustment.reconciles_adjustment_id == primary_id)).all()
            assert len(reversals) == 1 and reversals[0].amount == Decimal(amount) and reversals[0].kind == kind
            assert reversals[0].status == "recorded" and reversals[0].settled_at is None
        mysql57.evidence["financial_sequence"] = summary.model_dump(mode="json")


def test_real_settlement_vs_cancellation_race(engine, app, stay, provider, monkeypatch):
    from app.schemas.reservation_change_payment_schema import AdjustmentSettlementRequest
    provider["nightly"] = 120
    receipt = confirm(engine, app, stay, review(engine, app, stay))
    barrier = Barrier(2)
    original = app.booking_dao.lock_user_for_booking

    def synchronize(db, owner):
        barrier.wait(timeout=8)
        return original(db, owner)  # Real FOR UPDATE, with no replacement mutex.

    monkeypatch.setattr(app.booking_dao, "lock_user_for_booking", synchronize)

    def settle():
        with Session(engine) as db:
            return app.reservation_change_payment_service.settle_reservation_change_charge(
                db, AdjustmentSettlementRequest(accepted_amount="45.36", reservation_revision=1, accept_payment=True),
                receipt["adjustment"]["adjustment_id"], stay["owner"],
            )

    def cancel():
        with Session(engine) as db:
            return app.booking_service.cancel_booking(db, stay["reservation"], stay["owner"])

    calls_before = provider["calls"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(race_attempt, operation) for operation in (settle, cancel)]
        settlement, cancellation = [f.result(timeout=15) for f in futures]
    assert cancellation.status == "cancelled" and provider["calls"] == calls_before
    with Session(engine) as db:
        summary = app.reservation_change_payment_service.get_reservation_financial_summary(db, stay["reservation"], stay["owner"])
        adjustment = db.get(app.ReservationChangeAdjustment, receipt["adjustment"]["adjustment_id"])
        if settlement == 409:
            assert adjustment.status == "voided" and summary.reservation_revision == 2
            assert summary.cancellation_reconciliations == []
        else:
            assert adjustment.status == "paid" and summary.reservation_revision == 3
            assert summary.reconciliation_credits == 45.36
        assert summary.outstanding_additional_amount == 0
