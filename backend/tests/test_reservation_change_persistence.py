"""Persistence contracts only: isolated SQLite and compiled MySQL, no live DB."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import re
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Float, ForeignKeyConstraint, UniqueConstraint, create_engine, event, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.schema import AddConstraint, CreateColumn, CreateTable

from app.config.database import Base
from app.models import (
    Hotel, Payment, Reservation, ReservationChangeAdjustment, ReservationChangeEvent, RoomType, User,
)
from app.schemas.reservation_change_adjustment_schema import ReservationChangeAdjustmentRecord

ROOT = Path(__file__).parents[1] / "database"
MIGRATION = ROOT / "migrations/004_add_reservation_change_persistence.sql"
NOW = datetime(2026, 10, 9, 12, 0, 0, 123456)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(user_id=7, email="schema-owner@example.test", password_hash="hash"))
        session.add(Hotel(hotel_id=1, hotel_token="schema-property", name="Schema Hotel"))
        session.flush()
        session.add_all([RoomType(room_type_id=i, hotel_id=1, type_name="Rate", price_per_night=100) for i in (1, 2)])
        session.flush()
        session.add_all([
            Reservation(reservation_id=i, user_id=7, room_type_id=1, total_price=210,
                        check_in_date=date(2026, 11, 1), check_out_date=date(2026, 11, 3))
            for i in (1, 2)
        ])
        session.flush()
        session.add_all([Payment(payment_id=i, reservation_id=i, amount=226.8,
                                 payment_type="booking", payment_status="paid") for i in (1, 2)])
        session.commit()
        yield session
    engine.dispose()


def event_values(**overrides):
    values = dict(
        reservation_id=1, user_id=7, booking_payment_id=1, quote_jti=str(uuid4()),
        quote_sha256=b"q" * 32, request_sha256=b"r" * 32, original_state_sha256=b"s" * 32,
        revision_before=0, revision_after=1, old_room_type_id=1, new_room_type_id=2,
        old_check_in_date=date(2026, 11, 1), old_check_out_date=date(2026, 11, 3),
        new_check_in_date=date(2026, 11, 4), new_check_out_date=date(2026, 11, 6),
        old_reservation_total=Decimal("210.00"), new_reservation_total=Decimal("250.00"),
        old_payment_obligation=Decimal("226.80"), new_payment_obligation=Decimal("270.00"),
        booking_payment_status_before="paid", context_json={"q": "San Jose", "adults": 2, "children": 0},
        fresh_quote_json={"likehome_payment_amount": "270.00"}, response_json={"applied_revision": 1},
        quote_issued_at=NOW, quote_expires_at=NOW + timedelta(minutes=10),
    )
    values.update(overrides)
    return values


def add_event(db, **overrides):
    record = ReservationChangeEvent(**event_values(**overrides))
    db.add(record)
    db.flush()
    return record


def adjustment_values(change_id, **overrides):
    values = dict(change_id=change_id, kind="charge", amount=Decimal("43.20"), status="pending")
    values.update(overrides)
    return values


def unique_columns(table):
    return {tuple(constraint.columns.keys()) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}


def table_sql(source, name):
    source = re.sub(r"--[^\n]*", "", source)
    match = re.search(rf"CREATE TABLE\s+{name}\s*\(.*?\)\s*ENGINE=InnoDB;", source, re.S)
    assert match, name
    return match.group()


def normalized(sql):
    return re.sub(r"\s+", "", sql).lower().replace("`", "").replace("integer", "int").replace("numeric(", "decimal(")


def test_registration_and_revision_default_including_server_default(db):
    assert Base.metadata.tables["reservation_change_events"] is ReservationChangeEvent.__table__
    assert Base.metadata.tables["reservation_change_adjustments"] is ReservationChangeAdjustment.__table__
    assert db.get(Reservation, 1).revision == 0
    db.execute(text("INSERT INTO reservations (reservation_id,user_id,room_type_id,total_price,status,check_in_date,check_out_date,created_at) "
                    "VALUES (3,7,1,210,'confirmed','2026-11-10','2026-11-12',CURRENT_TIMESTAMP)"))
    assert db.get(Reservation, 3).revision == 0
    column = Reservation.__table__.c.revision
    assert not column.nullable and column.default.arg == 0 and column.server_default.arg == "0"
    assert column.type.dialect_impl(mysql.dialect()).unsigned
    indexes = {index.name: tuple(index.columns.keys()) for index in Reservation.__table__.indexes}
    assert indexes["ix_reservations_user_dates"] == ("user_id", "check_in_date", "check_out_date")


def test_event_fields_required_without_raw_tokens():
    table = ReservationChangeEvent.__table__
    assert set(table.columns.keys()) == set(event_values()) | {"change_id", "currency", "created_at"}
    assert all(not column.nullable for column in table.columns)
    assert not {"quote_id", "quote_token", "signed_quote", "raw_token"} & set(table.columns.keys())
    assert unique_columns(table) == {("quote_jti",), ("reservation_id", "revision_after")}
    assert {index.name: tuple(index.columns.keys()) for index in table.indexes}["ix_change_user"] == ("user_id", "change_id")
    for name in ("quote_sha256", "request_sha256", "original_state_sha256"):
        assert table.c[name].type.dialect_impl(mysql.dialect()).length == 32


def test_adjustment_fields_nullable_links_and_per_category_uniqueness():
    table = ReservationChangeAdjustment.__table__
    assert set(table.columns.keys()) == {
        "adjustment_id", "change_id", "entry_role", "reconciles_adjustment_id", "kind", "amount",
        "status", "created_at", "updated_at", "settled_at",
    }
    assert {column.name for column in table.columns if column.nullable} == {"reconciles_adjustment_id", "settled_at"}
    assert unique_columns(table) == {
        ("change_id", "entry_role"), ("reconciles_adjustment_id",), ("adjustment_id", "change_id"),
    }
    assert table.c.entry_role.default.arg == "price_change"
    assert table.c.kind.type.enums == ["charge", "credit"]
    assert table.c.status.type.enums == ["pending", "paid", "failed", "recorded", "voided"]


def test_money_precision_and_mysql_timestamp_types():
    for table, fields in [
        (ReservationChangeEvent.__table__, ["old_reservation_total", "new_reservation_total", "old_payment_obligation", "new_payment_obligation"]),
        (ReservationChangeAdjustment.__table__, ["amount"]),
    ]:
        assert table.dialect_options["mysql"]["engine"] == "InnoDB"
        for name in fields:
            column_type = table.c[name].type
            assert (column_type.precision, column_type.scale, column_type.asdecimal) == (10, 2, True)
        for column in table.columns:
            if column.name.endswith("_at"):
                assert column.type.dialect_impl(mysql.dialect()).fsp == 6


def test_foreign_keys_and_existing_ownership_are_preserved():
    event_targets = {fk.parent.name: fk.target_fullname for fk in ReservationChangeEvent.__table__.foreign_keys}
    assert event_targets == {
        "reservation_id": "reservations.reservation_id", "user_id": "users.user_id",
        "booking_payment_id": "payments.payment_id", "old_room_type_id": "room_types.room_type_id",
        "new_room_type_id": "room_types.room_type_id",
    }
    assert all(fk.ondelete == "RESTRICT" for fk in ReservationChangeEvent.__table__.foreign_keys)
    assert all(fk.ondelete == "RESTRICT" for fk in ReservationChangeAdjustment.__table__.foreign_keys)
    assert "user_id" not in Payment.__table__.columns
    assert not Payment.__table__.c.reservation_id.nullable and not Reservation.__table__.c.user_id.nullable
    assert Payment.__table__.c.payment_type.type.enums == ["booking", "cancellation"]
    # Existing fields stay together as Float until their runtime Decimal handling is adapted.
    assert all(isinstance(column.type, Float) for column in (
        Reservation.__table__.c.total_price, Payment.__table__.c.amount, RoomType.__table__.c.price_per_night,
    ))


def test_event_decimal_json_timestamp_round_trip_leaves_booking_unchanged(db):
    before = (db.get(Reservation, 1).check_in_date, db.get(Reservation, 1).total_price,
              db.get(Payment, 1).amount, db.get(Payment, 1).payment_status)
    record = add_event(db)
    record_id = record.change_id
    db.commit()
    db.expire_all()
    stored = db.get(ReservationChangeEvent, record_id)
    assert stored.old_payment_obligation == Decimal("226.80")
    assert isinstance(stored.new_payment_obligation, Decimal)
    assert stored.fresh_quote_json == {"likehome_payment_amount": "270.00"}
    assert stored.response_json == {"applied_revision": 1}
    assert stored.quote_issued_at == NOW
    assert stored.quote_expires_at - stored.quote_issued_at == timedelta(minutes=10)
    assert stored.currency == "USD"
    assert db.get(Reservation, 1).revision == 0
    assert (db.get(Reservation, 1).check_in_date, db.get(Reservation, 1).total_price,
            db.get(Payment, 1).amount, db.get(Payment, 1).payment_status) == before
    assert list(db.scalars(select(ReservationChangeAdjustment))) == []


@pytest.mark.parametrize("duplicate", ["quote", "revision"])
def test_database_rejects_duplicate_consumption_or_revision(db, duplicate):
    first = add_event(db)
    values = {"quote_jti": first.quote_jti, "revision_after": 2} if duplicate == "quote" else {}
    with pytest.raises(IntegrityError), db.begin_nested():
        add_event(db, **values)


@pytest.mark.parametrize("field", ["reservation_id", "user_id", "booking_payment_id", "old_room_type_id", "new_room_type_id"])
def test_database_rejects_event_orphans(db, field):
    with pytest.raises(IntegrityError), db.begin_nested():
        add_event(db, **{field: 999})


@pytest.mark.parametrize("field", ["context_json", "quote_issued_at", "new_payment_obligation", "quote_jti"])
def test_database_rejects_missing_required_event_values(db, field):
    with pytest.raises(IntegrityError), db.begin_nested():
        add_event(db, **{field: None})


def test_primary_and_compensating_entries_coexist_without_rewriting_history(db):
    change = add_event(db)
    original = ReservationChangeAdjustment(**adjustment_values(change.change_id, status="paid"))
    db.add(original)
    db.flush()
    compensation = ReservationChangeAdjustment(**adjustment_values(
        change.change_id, entry_role="cancellation_reconciliation", reconciles_adjustment_id=original.adjustment_id,
        kind="credit", status="recorded",
    ))
    db.add(compensation)
    db.commit()
    db.refresh(original)
    db.refresh(compensation)
    assert original.kind == "charge" and original.status == "paid" and original.amount == Decimal("43.20")
    assert compensation.kind == "credit" and compensation.status == "recorded"
    assert compensation.amount == Decimal("43.20")
    assert compensation.reconciles_adjustment_id == original.adjustment_id
    assert db.get(Payment, 1).amount == 226.8 and db.get(Payment, 1).payment_status == "paid"
    for values in [adjustment_values(change.change_id), adjustment_values(
        change.change_id, entry_role="cancellation_reconciliation", reconciles_adjustment_id=original.adjustment_id,
        kind="credit", status="recorded",
    )]:
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(ReservationChangeAdjustment(**values))
            db.flush()


def test_credit_reconciliation_support_and_cross_change_parent_rejection(db):
    first = add_event(db)
    second = add_event(db, reservation_id=2, booking_payment_id=2)
    credit = ReservationChangeAdjustment(**adjustment_values(first.change_id, kind="credit", status="recorded"))
    db.add(credit)
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(ReservationChangeAdjustment(**adjustment_values(
            second.change_id, entry_role="cancellation_reconciliation", reconciles_adjustment_id=credit.adjustment_id,
            status="recorded",
        )))
        db.flush()
    db.add(ReservationChangeAdjustment(**adjustment_values(
        first.change_id, entry_role="cancellation_reconciliation", reconciles_adjustment_id=credit.adjustment_id,
        status="recorded",
    )))
    db.flush()
    assert credit.status == "recorded"


def test_restrict_history_deletion_and_invalid_adjustment_event(db):
    change = add_event(db)
    db.add(ReservationChangeAdjustment(**adjustment_values(change.change_id)))
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.delete(change)
        db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(ReservationChangeAdjustment(**adjustment_values(999)))
        db.flush()


@pytest.mark.parametrize("field,value", [("kind", "refund"), ("status", "settled"), ("entry_role", "external_bank")])
def test_model_enums_reject_unsupported_values(db, field, value):
    change = add_event(db)
    with pytest.raises(StatementError), db.begin_nested():
        db.add(ReservationChangeAdjustment(**adjustment_values(change.change_id, **{field: value})))
        db.flush()


@pytest.mark.parametrize("kind,status", [("charge", status) for status in ("pending", "paid", "failed", "voided")] + [("credit", "recorded")])
def test_primary_input_contract_accepts_supported_lifecycle(kind, status):
    record = ReservationChangeAdjustmentRecord(change_id=1, kind=kind, status=status, amount="0.01")
    assert record.amount == Decimal("0.01")


@pytest.mark.parametrize("amount", ["0", "-0.01", "100000000", "0.001", "NaN", "Infinity"])
def test_input_guard_rejects_unsafe_or_non_cent_amounts(amount):
    with pytest.raises(ValidationError):
        ReservationChangeAdjustmentRecord(change_id=1, kind="charge", status="pending", amount=amount)


@pytest.mark.parametrize("overrides", [
    {"kind": "charge", "status": "recorded"}, {"kind": "credit", "status": "pending"},
    {"reconciles_adjustment_id": 1}, {"entry_role": "cancellation_reconciliation"},
    {"entry_role": "cancellation_reconciliation", "reconciles_adjustment_id": 1},
    {"change_id": True}, {"kind": "refund"}, {"amount": "1.00", "payment_type": "booking"},
])
def test_input_guard_rejects_invalid_roles_statuses_and_references(overrides):
    with pytest.raises(ValidationError):
        ReservationChangeAdjustmentRecord(**{**adjustment_values(1), **overrides})


@pytest.mark.parametrize("kind", ["charge", "credit"])
def test_internal_reconciliation_is_recorded_not_collectable(kind):
    record = ReservationChangeAdjustmentRecord(
        change_id=1, kind=kind, amount="43.20", status="recorded",
        entry_role="cancellation_reconciliation", reconciles_adjustment_id=1,
    )
    assert record.status == "recorded"


@pytest.mark.parametrize("model", [ReservationChangeEvent, ReservationChangeAdjustment])
def test_fresh_install_migration_and_mysql_model_contracts_agree(model):
    fresh = table_sql((ROOT / "like_home_database_init.sql").read_text(), model.__tablename__)
    upgraded = table_sql(MIGRATION.read_text(), model.__tablename__)
    assert normalized(fresh) == normalized(upgraded)
    compiled = normalized(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())))
    assert "engine=innodb" in compiled and "check(" not in compiled
    for column in model.__table__.columns:
        if column.primary_key:
            assert f"{column.name}intauto_incrementprimarykey" in normalized(fresh)
            continue
        rendered = normalized(str(CreateColumn(column).compile(dialect=mysql.dialect())))
        assert rendered in normalized(fresh), (column.name, rendered)
    for constraint in model.__table__.constraints:
        if isinstance(constraint, (UniqueConstraint, ForeignKeyConstraint)):
            rendered = str(AddConstraint(constraint, isolate_from_table=False).compile(dialect=mysql.dialect())).split(" ADD ", 1)[1]
            assert normalized(rendered) in normalized(fresh)
    for index in model.__table__.indexes:
        assert f"index{index.name}({','.join(index.columns.keys())})" in normalized(fresh)


def test_migration_is_additive_and_fresh_install_does_not_repeat_alterations():
    migration = MIGRATION.read_text()
    fresh = (ROOT / "like_home_database_init.sql").read_text()
    stripped = re.sub(r"--[^\n]*", "", migration)
    assert not re.search(r"\b(DROP|DELETE|UPDATE|INSERT|TRUNCATE)\s+(TABLE|FROM|INTO|reservations|payments)", stripped, re.I)
    assert "ADD COLUMN revision INT UNSIGNED NOT NULL DEFAULT 0" in migration
    assert "ADD INDEX ix_reservations_user_dates (user_id, check_in_date, check_out_date)" in migration
    assert "revision INT UNSIGNED NOT NULL DEFAULT 0" in fresh
    assert "INDEX ix_reservations_user_dates (user_id, check_in_date, check_out_date)" in fresh
    assert "ALTER TABLE" not in fresh
    assert "CHECK" not in stripped
    assert "SET time_zone = '+00:00';" in migration and "SET time_zone = '+00:00';" in fresh
