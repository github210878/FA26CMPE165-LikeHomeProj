"""Baseline financial reads: guarded synthetic SQLite, never live infrastructure."""

import json
import os
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User
from app.repositories import booking_dao, reservation_financial_summary_dao as dao
from app.routers.booking_router import router
from app.schemas.reservation_change_payment_schema import ReservationFinancialSummary
from app.services import booking_service, hotel_service, reservation_financial_summary_service as service
from app.utilities import auth, serpapi_client


def headers(user_id=7, role="user"):
    return {"Authorization": "Bearer " + auth.create_access_token(user_id, subject_type=role)}


def database_state(engine):
    """Compare raw values even when a malformed stored Enum cannot be decoded."""
    with engine.connect() as connection:
        result = {}
        for table in Base.metadata.sorted_tables:
            order = ",".join('"' + column.name + '"' for column in table.primary_key.columns)
            result[table.name] = [tuple(row) for row in connection.exec_driver_sql(
                f'SELECT * FROM "{table.name}" ORDER BY {order}'
            )]
        return result


@pytest.fixture
def summary_app(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            User(user_id=7, email="summary-owner@example.test", password_hash="synthetic-hash",
                 status="active", session_version=0, reward_points=37),
            User(user_id=8, email="summary-other@example.test", password_hash="synthetic-hash",
                 status="active", session_version=0, reward_points=89),
            Hotel(hotel_id=1, name="Synthetic hotel", hotel_token="synthetic-summary-property"),
            RoomType(room_type_id=1, hotel_id=1, type_name="Synthetic room", price_per_night=100),
            Reservation(reservation_id=1, user_id=7, room_type_id=1,
                        check_in_date=date(2026, 11, 1), check_out_date=date(2026, 11, 3),
                        guest_full_name="Synthetic Guest Contact", guest_email="guest-contact@example.test",
                        total_price=210, status="confirmed"),
            Payment(payment_id=1, reservation_id=1, amount=226.80,
                    payment_type="booking", payment_status="pending"),
        ])
        db.commit()
    monkeypatch.setattr(auth, "JWT_SECRET_KEY", "synthetic-financial-summary-test-secret-at-least-32")
    monkeypatch.setattr(auth, "JWT_ALGORITHM", "HS256")
    sql, session_states = [], []

    def forbidden(*args, **kwargs):
        pytest.fail("Financial summary attempted a write, provider or financial operation")

    for name in ("create_booking", "pay_booking_payment", "cancel_booking"):
        monkeypatch.setattr(booking_service, name, forbidden)
    for name in ("stage_booking_record", "add_reward_points_to_user"):
        monkeypatch.setattr(booking_dao, name, forbidden)
    monkeypatch.setattr(hotel_service, "revalidate_hotel", forbidden)
    monkeypatch.setattr(hotel_service, "search_hotels", forbidden)
    monkeypatch.setattr(serpapi_client, "search_google_hotels", forbidden)

    def select_only(connection, cursor, statement, parameters, context, many):
        assert statement.lstrip().upper().startswith("SELECT"), "Non-SELECT SQL during financial read"
        assert "FOR UPDATE" not in statement.upper()
        sql.append(statement)

    def isolated_db():
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA query_only=ON")
            event.listen(connection, "before_cursor_execute", select_only)
            try:
                with Session(bind=connection, autoflush=False) as db:
                    monkeypatch.setattr(db, "flush", forbidden)
                    monkeypatch.setattr(db, "commit", forbidden)
                    try:
                        yield db
                    finally:
                        session_states.append((len(db.new), len(db.dirty), len(db.deleted)))
            finally:
                event.remove(connection, "before_cursor_execute", select_only)
                connection.exec_driver_sql("PRAGMA query_only=OFF")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as client:
        def get(*, reservation_id=1, request_headers=None, params=None, content=None):
            before = database_state(engine)
            kwargs = {"headers": headers() if request_headers is None else request_headers}
            if params is not None:
                kwargs["params"] = params
            if content is not None:
                kwargs["content"] = content
            response = client.request("GET", f"/bookings/{reservation_id}/financial-summary", **kwargs)
            assert database_state(engine) == before
            assert all(state == (0, 0, 0) for state in session_states)
            return response
        yield SimpleNamespace(get=get, engine=engine, sql=sql, app=app)
    engine.dispose()


def change(app, model, identity=1, **changes):
    with Session(app.engine) as db:
        record = db.get(model, identity)
        for field, value in changes.items():
            setattr(record, field, value)
        db.commit()


def cancel(app, *, original="refunded", fee_status="pending", fee=42):
    change(app, Reservation, status="cancelled")
    change(app, Payment, payment_status=original)
    with Session(app.engine) as db:
        db.add(Payment(payment_id=2, reservation_id=1, amount=fee,
                       payment_type="cancellation", payment_status=fee_status))
        db.commit()


def baseline():
    return {
        "reservation_id": 1, "reservation_revision": 0, "reservation_status": "confirmed",
        "currency": "USD", "latest_change_id": None,
        "current_reservation_total": 210.0, "current_booking_obligation": 226.8,
        "original_booking_payment": {"payment_id": 1, "reservation_id": 1, "amount": 226.8,
                                     "payment_type": "booking", "payment_status": "pending"},
        "paid_additional_charges": 0.0, "pending_additional_charges": 0.0,
        "failed_additional_charges": 0.0, "recorded_internal_credits": 0.0,
        "outstanding_additional_amount": 0.0, "adjustments": [],
        "voided_additional_charges": 0.0, "cancellation_reconciliations": [],
        "reconciliation_credits": 0.0, "reconciliation_debits": 0.0,
        "cancellation_payment": None, "outstanding_cancellation_amount": 0.0,
        "outstanding_booking_amount": 226.8,
    }


def test_owner_gets_complete_typed_baseline_from_two_read_queries(summary_app):
    response = summary_app.get()
    assert response.status_code == 200
    assert response.json() == baseline()
    parsed = ReservationFinancialSummary.model_validate(response.json())
    assert parsed.model_dump(mode="json") == response.json()
    assert json.loads(parsed.model_dump_json()) == response.json()
    assert len(summary_app.sql) == 2  # Existing authentication + one joined financial SELECT.
    projection = summary_app.sql[-1].lower()
    assert "reservations" in projection and "payments" in projection
    for excluded in ("guest_full_name", "guest_email", "adjustments", "reservation_changes", "revision", "room_types", "hotels"):
        assert excluded not in projection
    for excluded in ("guest-contact@example.test", "Synthetic Guest Contact", "summary-owner@example.test", "synthetic-hash", "reward_points"):
        assert excluded not in response.text


@pytest.mark.parametrize("reservation_status", ["confirmed", "completed"])
@pytest.mark.parametrize("payment_status,outstanding", [("pending", 226.8), ("paid", 0), ("failed", 226.8)])
def test_active_and_completed_outstanding_follows_recorded_payment(summary_app, reservation_status, payment_status, outstanding):
    change(summary_app, Reservation, status=reservation_status)
    change(summary_app, Payment, payment_status=payment_status)
    response = summary_app.get()
    assert response.status_code == 200
    body = response.json()
    assert body["reservation_status"] == reservation_status
    assert body["original_booking_payment"]["payment_status"] == payment_status
    assert body["current_booking_obligation"] == 226.8
    assert body["outstanding_booking_amount"] == outstanding
    assert body["cancellation_payment"] is None
    assert body["outstanding_cancellation_amount"] == 0


def test_completed_historical_stay_needs_no_new_quote_or_future_dates(summary_app):
    change(summary_app, Reservation, status="completed", check_in_date=date(2020, 1, 1), check_out_date=date(2020, 1, 3))
    change(summary_app, Payment, payment_status="paid")
    assert summary_app.get().status_code == 200


@pytest.mark.parametrize("original", ["pending", "refunded"])
@pytest.mark.parametrize("fee_status,outstanding", [("pending", 42), ("failed", 42), ("paid", 0), ("refunded", 0)])
def test_cancelled_summary_preserves_both_payments_without_reinstating_original_debt(summary_app, original, fee_status, outstanding):
    cancel(summary_app, original=original, fee_status=fee_status)
    response = summary_app.get()
    assert response.status_code == 200
    body = response.json()
    assert body["reservation_status"] == "cancelled"
    assert body["original_booking_payment"]["payment_status"] == original
    assert body["original_booking_payment"]["amount"] == 226.8
    assert body["current_booking_obligation"] == 226.8
    assert body["outstanding_booking_amount"] == 0
    assert body["cancellation_payment"] == {"payment_id": 2, "reservation_id": 1, "amount": 42.0,
                                            "payment_type": "cancellation", "payment_status": fee_status}
    assert body["outstanding_cancellation_amount"] == outstanding
    assert ReservationFinancialSummary.model_validate(body).model_dump(mode="json") == body


def test_stored_amounts_are_not_repriced_by_current_tax_or_cancellation_policy(summary_app):
    change(summary_app, Payment, amount=219.73)
    cancel(summary_app, fee=41.99)
    response = summary_app.get()
    assert response.status_code == 200
    body = response.json()
    assert body["current_reservation_total"] == 210
    assert body["current_booking_obligation"] == 219.73
    assert body["cancellation_payment"]["amount"] == 41.99
    assert body["outstanding_cancellation_amount"] == 41.99


@pytest.mark.parametrize("amount", [Decimal("0.01"), Decimal("0.29"), Decimal("19.99"), Decimal("226.80"), Decimal("99999999.99")])
def test_stored_cent_values_survive_numeric_json_without_float_arithmetic(summary_app, amount):
    change(summary_app, Reservation, total_price=float(amount))
    change(summary_app, Payment, amount=float(amount))
    response = summary_app.get()
    assert response.status_code == 200
    for key in ("current_reservation_total", "current_booking_obligation", "outstanding_booking_amount"):
        assert isinstance(response.json()[key], (int, float))
        assert Decimal(str(response.json()[key])) == amount


def test_zero_cent_cancellation_charge_is_representable_without_inventing_a_minimum(summary_app):
    change(summary_app, Reservation, total_price=0.01)
    change(summary_app, Payment, amount=0.01)
    cancel(summary_app, original="pending", fee=0)
    response = summary_app.get()
    assert response.status_code == 200
    assert response.json()["cancellation_payment"]["amount"] == 0
    assert response.json()["outstanding_cancellation_amount"] == 0
    assert response.json()["outstanding_booking_amount"] == 0


def test_missing_and_non_owned_reservations_have_identical_404(summary_app):
    missing = summary_app.get(reservation_id=999)
    nonowner = summary_app.get(request_headers=headers(8))
    assert missing.status_code == nonowner.status_code == 404
    assert missing.json() == nonowner.json() == {"detail": "Reservation not found"}


def test_another_reservations_payment_never_enters_the_summary(summary_app):
    with Session(summary_app.engine) as db:
        db.add(Reservation(reservation_id=2, user_id=8, room_type_id=1,
                           check_in_date=date(2026, 12, 1), check_out_date=date(2026, 12, 3),
                           total_price=987.65, status="confirmed"))
        db.add(Payment(payment_id=2, reservation_id=2, amount=987.65,
                       payment_type="booking", payment_status="paid"))
        db.commit()
    assert summary_app.get().json() == baseline()
    assert summary_app.get(reservation_id=2).status_code == 404


@pytest.mark.parametrize("credentials", ["absent", "malformed", "partner", "missing-user"])
def test_authentication_boundaries(summary_app, credentials):
    request_headers = {"absent": {}, "malformed": {"Authorization": "Bearer invalid"},
                       "partner": headers(7, "partner"), "missing-user": headers(999)}[credentials]
    response = summary_app.get(request_headers=request_headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("changes", [{"status": "deleted"}, {"session_version": 1}])
def test_inactive_and_revoked_customer_sessions_are_rejected(summary_app, changes):
    change(summary_app, User, identity=7, **changes)
    assert summary_app.get().status_code == 401


@pytest.mark.parametrize("identity", [{"user_id": "7"}, {"customer_id": "7"}, {"reservation_id": "1"}, {"amount": "0.01"}])
def test_query_parameters_cannot_supply_identity_or_financial_context(summary_app, identity):
    assert summary_app.get(params=identity).status_code == 422
    assert summary_app.get(params=identity, request_headers=headers(8)).status_code == 422


@pytest.mark.parametrize("body", ['{"user_id":7}', '{"customer_id":7}', '{"amount":0.01}', '{}', 'null'])
def test_get_endpoint_accepts_no_request_body(summary_app, body):
    assert summary_app.get(content=body).status_code == 422


@pytest.mark.parametrize("identity", [0, -1, "not-an-id", "1.5", 9007199254740992])
def test_invalid_reservation_identifiers(summary_app, identity):
    assert summary_app.get(reservation_id=identity).status_code == 422


@pytest.mark.parametrize("history", ["missing", "duplicate-booking", "duplicate-cancellation", "cancellation-only",
                                     "active-cancellation", "cancelled-without-fee", "cancelled-paid-original",
                                     "cancelled-failed-original", "active-refunded-original"])
def test_ambiguous_or_inconsistent_histories_fail_closed(summary_app, history):
    with Session(summary_app.engine) as db:
        payment = db.get(Payment, 1)
        reservation = db.get(Reservation, 1)
        if history == "missing":
            db.delete(payment)
        elif history == "cancellation-only":
            payment.payment_type = "cancellation"
        elif history == "cancelled-without-fee":
            reservation.status = "cancelled"
        elif history == "active-refunded-original":
            payment.payment_status = "refunded"
        else:
            kind = "booking" if history == "duplicate-booking" else "cancellation"
            db.add(Payment(payment_id=2, reservation_id=1, amount=42, payment_type=kind, payment_status="pending"))
            if history == "duplicate-cancellation":
                reservation.status = "cancelled"
                db.add(Payment(payment_id=3, reservation_id=1, amount=42, payment_type="cancellation", payment_status="pending"))
            if history.startswith("cancelled-"):
                reservation.status = "cancelled"
                payment.payment_status = "paid" if history == "cancelled-paid-original" else "failed"
        db.commit()
    response = summary_app.get()
    assert response.status_code == 409
    assert response.json() == {"detail": "Reservation financial state cannot be verified"}


@pytest.mark.parametrize("table,column,value", [
    ("reservations", "total_price", 0), ("reservations", "total_price", -0.01),
    ("reservations", "total_price", 210.001), ("reservations", "total_price", float("inf")),
    ("payments", "amount", 0), ("payments", "amount", -1), ("payments", "amount", 226.801),
    ("payments", "amount", 100000000), ("payments", "amount", "bad-money"),
    ("payments", "amount", float("-inf")),
])
def test_malformed_persisted_money_is_not_rounded_or_invented(summary_app, table, column, value):
    # Raw SQLite setup deliberately represents malformed legacy storage, not a
    # supported application write or a claim that MySQL accepts these values.
    with summary_app.engine.begin() as connection:
        connection.exec_driver_sql(f"UPDATE {table} SET {column} = ?", (value,))
    assert summary_app.get().status_code == 409


@pytest.mark.parametrize("amount", [-0.01, 42.001, 100000000, "bad-fee"])
def test_invalid_cancellation_amount_is_not_replaced_with_a_calculated_fee(summary_app, amount):
    cancel(summary_app)
    with summary_app.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE payments SET amount = ? WHERE payment_id = 2", (amount,))
    assert summary_app.get().status_code == 409


@pytest.mark.parametrize("value", [True, False, "226.80", None, Decimal("NaN"), Decimal("Infinity"), Decimal("-0.01"), Decimal("0.001")])
def test_money_guard_rejects_coercion_and_non_cent_values(value):
    with pytest.raises((ValueError, ArithmeticError)):
        service._money(value)


@pytest.mark.parametrize("table,column,value", [("payments", "payment_type", "adjustment"),
                                              ("payments", "payment_status", "unknown"),
                                              ("reservations", "status", "unknown")])
def test_unknown_persisted_enums_fail_with_safe_error(summary_app, table, column, value):
    with summary_app.engine.begin() as connection:
        connection.exec_driver_sql(f"UPDATE {table} SET {column} = ?", (value,))
    response = summary_app.get()
    assert response.status_code == 409
    assert response.json() == {"detail": "Reservation financial state cannot be verified"}


@pytest.mark.parametrize("field,value", [("payment_id", 0), ("payment_id", True), ("payment_reservation_id", 2),
                                       ("amount", None), ("payment_type", "adjustment"), ("payment_status", "unknown")])
def test_unverifiable_payment_projections_fail_closed(summary_app, monkeypatch, field, value):
    original = dao.get_owned_financial_rows
    def changed(db, reservation_id, user_id):
        rows = [dict(row) for row in original(db, reservation_id, user_id)]
        rows[0][field] = value
        return rows
    monkeypatch.setattr(dao, "get_owned_financial_rows", changed)
    assert summary_app.get().status_code == 409


@pytest.mark.parametrize("cancelled", [False, True])
def test_revision_and_empty_history_are_explicit_pre_change_conventions(summary_app, cancelled):
    if cancelled:
        cancel(summary_app)
    response = summary_app.get()
    assert response.status_code == 200
    body = response.json()
    assert type(body["reservation_revision"]) is int and body["reservation_revision"] == 0
    assert body["latest_change_id"] is None
    assert body["adjustments"] == body["cancellation_reconciliations"] == []
    for field in ("paid_additional_charges", "pending_additional_charges", "failed_additional_charges",
                  "recorded_internal_credits", "outstanding_additional_amount", "voided_additional_charges",
                  "reconciliation_credits", "reconciliation_debits"):
        assert body[field] == 0
    assert "revision" not in Reservation.__table__.columns
    assert not any("adjustment" in name or "reservation_change" in name for name in Base.metadata.tables)


def test_database_error_is_sanitized_without_fallback_summary(summary_app, monkeypatch, caplog):
    def fail(*args):
        raise SQLAlchemyError("private database credentials and customer data")
    monkeypatch.setattr(dao, "get_owned_financial_rows", fail)
    response = summary_app.get()
    assert response.status_code == 503
    assert response.json() == {"detail": "Financial summary is temporarily unavailable"}
    assert "private" not in response.text and "private" not in caplog.text
    assert "original_booking_payment" not in response.json()


def test_projection_read_does_not_autoflush_unrelated_pending_state(summary_app):
    before = database_state(summary_app.engine)
    with Session(summary_app.engine, autoflush=True) as db:
        db.add(Payment(reservation_id=1, amount=0.01, payment_type="cancellation", payment_status="pending"))
        rows = dao.get_owned_financial_rows(db, 1, 7)
        assert len(rows) == 1 and len(db.new) == 1
    assert database_state(summary_app.engine) == before


FRONTEND_VALIDATOR = r'''
const fs = require('node:fs'), vm = require('node:vm');
const root = process.argv[1];
const ts = require(root + '/node_modules/typescript/lib/typescript.js');
const text = fs.readFileSync(root + '/lib/bookings.ts', 'utf8');
const tree = ts.createSourceFile('bookings.ts', text, ts.ScriptTarget.Latest, true);
const functions = tree.statements.filter(node => ts.isFunctionDeclaration(node) &&
  !node.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.AsyncKeyword));
const context = vm.createContext({ exports: {} });
vm.runInContext(ts.transpileModule(functions.map(node => node.getText(tree)).join('\n'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, context, {timeout: 1000});
const body = JSON.parse(fs.readFileSync(0, 'utf8'));
if (context.isReservationFinancialSummary(body, 1) !== true)
  throw new Error('Actual endpoint JSON rejected by unchanged frontend financial validator');
process.stdout.write('compatible');
'''


@pytest.mark.parametrize("kind", ["confirmed-pending", "confirmed-paid", "completed", "cancelled-refunded", "cancelled-pending"])
def test_actual_response_passes_unchanged_frontend_validator(summary_app, kind):
    if kind.startswith("cancelled"):
        cancel(summary_app, original="pending" if kind.endswith("pending") else "refunded")
    elif kind == "completed":
        change(summary_app, Reservation, status="completed")
        change(summary_app, Payment, payment_status="paid")
    elif kind == "confirmed-paid":
        change(summary_app, Payment, payment_status="paid")
    response = summary_app.get()
    assert response.status_code == 200
    node = shutil.which("node")
    assert node is not None, "Existing Node environment is required for offline compatibility verification"
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "likehome"
    # Only pure validators are evaluated in a VM without fetch/require. No
    # frontend app, API/auth module or external provider is imported or mounted.
    result = subprocess.run([node, "-e", FRONTEND_VALIDATOR, str(frontend)], input=response.text,
                            capture_output=True, text=True, timeout=20, check=False,
                            env={"PATH": os.environ.get("PATH", "")})
    assert result.returncode == 0, result.stderr
    assert result.stdout == "compatible"
