"""Isolated settlement/summary tests: SQLite, mock provider, no real payments.

Threaded contention uses the existing explicitly simulated User-row mutex around
real file-backed SQLite Sessions. This does not verify MySQL/InnoDB contention.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, timezone
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models import Payment, Reservation, ReservationChangeAdjustment, ReservationChangeEvent, User
from app.repositories import booking_dao
from app.schemas.reservation_change_payment_schema import AdjustmentSettlementRequest
from app.services import booking_service, reservation_change_payment_service as finance
from app.utilities import auth, serpapi_client

from test_reservation_change_confirmation import confirm, confirmation, review, snapshot, threaded_database
from test_reservation_change_quotes import NOW, quote_app


def make_charge(engine):
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.get(Payment, 1).amount = 100
        db.commit()
    return confirm(engine, confirmation(review(engine)))


def acknowledgement(*, amount=Decimal("81.44"), revision=1, **changes):
    return AdjustmentSettlementRequest(accepted_amount=amount, reservation_revision=revision, accept_payment=True, **changes)


def settle(engine, request=None, *, adjustment_id=1, user_id=7, now=NOW):
    with Session(engine) as db:
        return finance.settle_reservation_change_charge(db, request or acknowledgement(), adjustment_id, user_id, now=now)


def summary(engine, *, reservation_id=1, user_id=7):
    with Session(engine) as db:
        return finance.get_reservation_financial_summary(db, reservation_id, user_id)


def assert_rejected(engine, request=None, *, expected=409, **kwargs):
    before = snapshot(engine)
    with pytest.raises(HTTPException) as error:
        settle(engine, request, **kwargs)
    assert error.value.status_code == expected
    assert snapshot(engine) == before


@pytest.fixture
def charge(quote_app):
    receipt = make_charge(quote_app[1])
    assert receipt["adjustment"]["adjustment_id"] == 1
    return quote_app


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_charge_settlement_and_repeat_preserve_booking_and_immutable_history(charge, status):
    _, engine, calls, _ = charge
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, 1).status = status
        db.commit()
    before = snapshot(engine)
    provider_count = len(calls)
    result = settle(engine)
    assert result.amount == 81.44 and result.status == "paid" and result.kind == "charge"
    assert result.adjustment_id == result.change_id == result.reservation_id == 1
    assert result.settled_at == NOW
    assert result.model_dump(mode="json")["amount"] == 81.44
    assert settle(engine).model_dump(mode="json") == result.model_dump(mode="json")
    assert len(calls) == provider_count
    after = snapshot(engine)
    assert after["payments"] == before["payments"]
    assert after["reservation_change_events"] == before["reservation_change_events"]
    for table in ("users", "hotels", "room_types"):
        assert after[table] == before[table]
    original_reservation = before["reservations"][0]
    assert after["reservations"][0] == {**original_reservation, "revision": 2}
    adjustment = after["reservation_change_adjustments"][0]
    assert adjustment == {**before["reservation_change_adjustments"][0], "status": "paid",
                          "settled_at": NOW.replace(tzinfo=None), "updated_at": NOW.replace(tzinfo=None)}


@pytest.mark.parametrize("user_id,adjustment_id,expected", [(8, 1, 404), (7, 999, 404), (999, 1, 401), (True, 1, 401), ("7", 1, 401)])
def test_nonowner_missing_and_invalid_user_boundaries(charge, user_id, adjustment_id, expected):
    _, engine, calls, _ = charge
    count = len(calls)
    assert_rejected(engine, expected=expected, user_id=user_id, adjustment_id=adjustment_id)
    assert len(calls) == count


def test_owner_scoped_detail_and_summary_do_not_write(charge):
    _, engine, calls, _ = charge
    before = snapshot(engine)
    count = len(calls)
    with Session(engine) as db:
        detail = finance.get_owned_adjustment_detail(db, 1, 7)
        assert detail.amount == 81.44 and detail.status == "pending" and detail.settled_at is None
        assert detail.reservation_id == detail.change_id == 1
        finance.get_reservation_financial_summary(db, 1, 7)
        assert not db.new and not db.dirty
    for operation in (finance.get_owned_adjustment_detail, finance.get_reservation_financial_summary):
        with Session(engine) as db, pytest.raises(HTTPException) as error:
            operation(db, 1, 8)
        assert error.value.status_code == 404
        with Session(engine) as db, pytest.raises(HTTPException) as error:
            operation(db, 999, 7)
        assert error.value.status_code == 404
    assert snapshot(engine) == before and len(calls) == count


def test_existing_customer_authentication_and_partner_separation_with_test_only_routes(charge):
    """Wire existing auth only in this disposable app; production routes stay absent."""
    _, engine, _, _ = charge
    app = FastAPI()

    def isolated_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db

    @app.post("/test-only/adjustments/{adjustment_id}")
    def pay(adjustment_id: int, body: AdjustmentSettlementRequest,
            db: Session = Depends(get_db), user_id: int = Depends(auth.get_current_user_id)):
        return finance.settle_reservation_change_charge(db, body, adjustment_id, user_id, now=NOW)

    body = acknowledgement().model_dump(mode="json")
    before = snapshot(engine)
    with TestClient(app) as client:
        path = "/test-only/adjustments/1"
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, json=body, headers={"Authorization": "Bearer invalid"}).status_code == 401
        for user_id, role, expected in [(7, "partner", 401), (8, "user", 404)]:
            headers = {"Authorization": f"Bearer {auth.create_access_token(user_id, subject_type=role)}"}
            assert client.post(path, json=body, headers=headers).status_code == expected
        headers = {"Authorization": f"Bearer {auth.create_access_token(7, subject_type='user')}"}
        assert client.post(path, json={**body, "user_id": 8}, headers=headers).status_code == 422
        assert snapshot(engine) == before
        assert client.post(path, json=body, headers=headers).json()["status"] == "paid"


@pytest.mark.parametrize("changes", [
    {"accepted_amount": 1}, {"accepted_amount": Decimal("81.45")},
    {"reservation_revision": 0}, {"reservation_revision": 2},
])
def test_stale_or_wrong_review_cannot_authorize_payment(charge, changes):
    _, engine, _, _ = charge
    request = AdjustmentSettlementRequest(**{**acknowledgement().model_dump(), **changes})
    assert_rejected(engine, request)


@pytest.mark.parametrize("changes", [
    {"accepted_amount": True}, {"accepted_amount": float("nan")}, {"accepted_amount": 0},
    {"accepted_amount": Decimal("100000000")}, {"reservation_revision": True},
    {"reservation_revision": -1}, {"accept_payment": False}, {"accept_payment": "true"},
    {"amount": 1}, {"user_id": 7},
])
def test_payment_acknowledgement_schema_fails_closed(changes):
    values = {"accepted_amount": 81.44, "reservation_revision": 1, "accept_payment": True, **changes}
    with pytest.raises(ValidationError):
        AdjustmentSettlementRequest(**values)


def test_unvalidated_internal_request_is_revalidated(charge):
    request = acknowledgement().model_copy(update={"accept_payment": False})
    assert_rejected(charge[1], request, expected=422)


@pytest.mark.parametrize("case", ["voided", "recorded_charge", "paid_without_timestamp", "pending_with_timestamp", "credit", "parent", "reconciliation", "wrong_amount", "cancelled", "completed", "unpaid_booking", "changed_booking_amount", "max_revision"])
def test_invalid_or_inconsistent_charge_is_not_settled(charge, case):
    _, engine, _, _ = charge
    with Session(engine) as db:
        row = db.get(ReservationChangeAdjustment, 1)
        reservation = db.get(Reservation, 1)
        if case == "voided":
            row.status = "voided"
        elif case == "recorded_charge":
            row.status = "recorded"
        elif case == "paid_without_timestamp":
            row.status = "paid"
        elif case == "pending_with_timestamp":
            row.settled_at = NOW.replace(tzinfo=None)
        elif case == "credit":
            row.kind, row.status = "credit", "recorded"
        elif case == "parent":
            row.reconciles_adjustment_id = row.adjustment_id
        elif case == "reconciliation":
            row.entry_role = "cancellation_reconciliation"
            row.status = "recorded"
            row.reconciles_adjustment_id = row.adjustment_id
        elif case == "wrong_amount":
            row.amount = Decimal("81.45")
        elif case in ("cancelled", "completed"):
            reservation.status = case
        elif case == "unpaid_booking":
            db.get(Payment, 1).payment_status = "pending"
        elif case == "changed_booking_amount":
            db.get(Payment, 1).amount = 101
        else:
            reservation.revision = 4294967295
        db.commit()
    request = acknowledgement(revision=4294967295) if case == "max_revision" else acknowledgement()
    assert_rejected(engine, request)


@pytest.mark.parametrize("case", ["event_owner", "event_reservation", "missing_event"])
def test_invalid_ownership_associations_are_private(charge, case):
    _, engine, _, _ = charge
    with Session(engine) as db:
        if case == "event_owner":
            db.get(ReservationChangeEvent, 1).user_id = 8
        elif case == "event_reservation":
            db.add(Reservation(reservation_id=2, user_id=8, room_type_id=2, total_price=100,
                               check_in_date=date(2026, 11, 4), check_out_date=date(2026, 11, 6), status="confirmed"))
            db.get(ReservationChangeEvent, 1).reservation_id = 2
        else:
            db.get(ReservationChangeAdjustment, 1).change_id = 999
        db.commit()
    assert_rejected(engine, expected=404)


@pytest.mark.parametrize("field,value", [
    ("booking_payment_id", 999), ("revision_after", 2), ("currency", "EUR"),
    ("new_reservation_total", Decimal("168.01")), ("new_payment_obligation", Decimal("181.45")),
    ("new_room_type_id", 2), ("new_check_out_date", date(2026, 11, 7)),
])
def test_inconsistent_committed_event_cannot_authorize_payment(charge, field, value):
    _, engine, _, _ = charge
    with Session(engine) as db:
        setattr(db.get(ReservationChangeEvent, 1), field, value)
        db.commit()
    assert_rejected(engine)


def test_real_recorded_credit_cannot_be_paid(quote_app):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.commit()
    confirm(engine, confirmation(review(engine)))
    assert summary(engine).recorded_internal_credits == 45.36
    assert_rejected(engine, acknowledgement(amount=45.36))


@pytest.mark.parametrize("status", ["pending", "paid"])
def test_unchanged_reservation_summary(quote_app, status):
    _, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = status
        db.commit()
    result = summary(engine)
    assert result.current_reservation_total == 210 and result.current_booking_obligation == 226.8
    assert result.original_booking_payment.amount == 226.8 and result.original_booking_payment.payment_status == status
    assert result.latest_change_id is None and result.adjustments == []
    assert result.paid_additional_charges == result.pending_additional_charges == result.recorded_internal_credits == 0
    assert result.outstanding_additional_amount == 0 and calls == []


def test_unpaid_revised_obligation_summary_preserves_original_payment_record(quote_app):
    _, engine, calls, _ = quote_app
    confirm(engine, confirmation(review(engine)))
    result = summary(engine)
    assert result.current_reservation_total == 168 and result.current_booking_obligation == 181.44
    assert result.original_booking_payment.payment_id == 1 and result.original_booking_payment.amount == 181.44
    assert result.original_booking_payment.payment_status == "pending"
    assert result.adjustments == [] and result.outstanding_additional_amount == 0 and len(calls) == 2


def test_pending_settled_and_failed_charge_summary_buckets(charge):
    _, engine, _, _ = charge
    pending = summary(engine)
    assert pending.original_booking_payment.amount == 100 and pending.original_booking_payment.payment_status == "paid"
    assert pending.current_booking_obligation == 181.44 and pending.current_reservation_total == 168
    assert pending.pending_additional_charges == pending.outstanding_additional_amount == 81.44
    assert pending.paid_additional_charges == pending.failed_additional_charges == pending.recorded_internal_credits == 0
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, 1).status = "failed"
        db.commit()
    failed = summary(engine)
    assert failed.failed_additional_charges == failed.outstanding_additional_amount == 81.44
    assert failed.pending_additional_charges == 0 and failed.adjustments[0].status == "failed"
    settle(engine)
    paid = summary(engine)
    assert paid.paid_additional_charges == 81.44 and paid.outstanding_additional_amount == 0
    assert paid.pending_additional_charges == paid.failed_additional_charges == 0
    assert paid.reservation_revision == 2 and paid.adjustments[0].settled_at == NOW


def test_multiple_sequential_changes_and_settlements_do_not_net_or_double_count(quote_app):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.commit()
    first = confirm(engine, confirmation(review(engine)))  # credit 45.36
    second = confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")))
    settle(engine, acknowledgement(amount=90.72, revision=2), adjustment_id=second["adjustment"]["adjustment_id"])
    third = confirm(engine, confirmation(review(engine, check_in_date="2026-11-15", check_out_date="2026-11-19")))
    before = summary(engine)
    assert before.paid_additional_charges == before.pending_additional_charges == before.outstanding_additional_amount == 90.72
    assert before.recorded_internal_credits == 45.36
    settle(engine, acknowledgement(amount=90.72, revision=4), adjustment_id=third["adjustment"]["adjustment_id"])
    fourth = confirm(engine, confirmation(review(engine, check_in_date="2026-11-22", check_out_date="2026-11-24")))
    after = summary(engine)
    assert after.current_booking_obligation == 181.44 and after.original_booking_payment.amount == 226.8
    assert after.paid_additional_charges == 181.44 and after.recorded_internal_credits == 226.8
    assert after.outstanding_additional_amount == 0 and after.pending_additional_charges == 0
    assert after.reservation_revision == 6 and len(after.adjustments) == 4
    assert first["adjustment"]["kind"] == fourth["adjustment"]["kind"] == "credit"
    assert len({row.adjustment_id for row in after.adjustments}) == 4
    with Session(engine) as db:
        assert len(db.scalars(select(Payment)).all()) == 1
        assert len(db.scalars(select(ReservationChangeEvent)).all()) == 4


def test_pending_change_then_original_pay_then_additional_settlement(quote_app):
    _, engine, _, _ = quote_app
    confirm(engine, confirmation(review(engine)))
    with Session(engine) as db:
        booking_service.pay_booking_payment(db, 1, 7)
    change = confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")))
    settle(engine, acknowledgement(amount=90.72, revision=3), adjustment_id=change["adjustment"]["adjustment_id"])
    result = summary(engine)
    assert result.current_booking_obligation == 272.16 and result.original_booking_payment.amount == 181.44
    assert result.paid_additional_charges == 90.72 and result.reservation_revision == 4


def test_cent_rounding_and_utc_are_stable(charge):
    _, engine, _, _ = charge
    local = NOW.astimezone(timezone(timedelta(hours=-7)))
    result = settle(engine, acknowledgement(amount=81.44 + 1e-12), now=local)
    assert result.amount == 81.44 and result.settled_at == NOW
    assert settle(engine).model_dump(mode="json") == result.model_dump(mode="json")
    with Session(engine) as db:
        assert db.get(ReservationChangeAdjustment, 1).amount == Decimal("81.44")


def test_paid_retry_remains_read_only_after_later_change_and_rejects_changed_amount(charge):
    _, engine, calls, _ = charge
    result = settle(engine)
    confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")))
    count = len(calls)
    before = snapshot(engine)
    assert settle(engine) == result
    assert snapshot(engine) == before and len(calls) == count
    assert_rejected(engine, acknowledgement(amount=81.45))
    assert_rejected(engine, acknowledgement(revision=99))


def test_cancelled_ledger_summary_rejects_unreconciled_legacy_state(charge):
    _, engine, _, _ = charge
    with Session(engine) as db:
        # A legacy/incomplete cancellation deliberately lacks ledger treatment
        # and a cancellation payment. The normal service now reconciles both.
        db.get(Reservation, 1).status = "cancelled"
        db.get(Payment, 1).payment_status = "refunded"
        db.commit()
    before = snapshot(engine)
    with pytest.raises(HTTPException) as error:
        summary(engine)
    assert error.value.status_code == 409 and "cancellation reconciliation" in error.value.detail
    assert_rejected(engine)
    assert snapshot(engine) == before


def test_existing_cancellation_summary_without_adjustments(quote_app):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        result = booking_service.cancel_booking(db, 1, 7)
        assert result.cancellation_amount == 42
    value = summary(engine)
    assert value.reservation_status == "cancelled" and value.outstanding_additional_amount == 0
    assert value.original_booking_payment.amount == 226.8 and value.current_booking_obligation == 226.8


@pytest.mark.parametrize("failure", ["commit", "flush", "deadlock"])
def test_failed_settlement_rolls_back_revision_status_and_timestamps(charge, monkeypatch, failure):
    _, engine, _, _ = charge
    before = snapshot(engine)
    with Session(engine) as db:
        if failure == "commit":
            def failed_commit():
                db.flush()
                assert db.get(Reservation, 1).revision == 2
                assert db.get(ReservationChangeAdjustment, 1).status == "paid"
                raise SQLAlchemyError("injected commit failure")
            monkeypatch.setattr(db, "commit", failed_commit)
        elif failure == "flush":
            def after_flush(*_):
                raise RuntimeError("injected after UPDATE")
            event.listen(db, "after_flush", after_flush)
        else:
            monkeypatch.setattr(booking_dao, "lock_payments_for_change", lambda *_: (_ for _ in ()).throw(OperationalError("lock", {}, Exception("deadlock"))))
        with pytest.raises(HTTPException) as error:
            finance.settle_reservation_change_charge(db, acknowledgement(), 1, 7, now=NOW)
        assert error.value.status_code == 500 and not db.in_transaction()
    assert snapshot(engine) == before


def test_settlement_lock_order_and_single_commit(charge, monkeypatch):
    from sqlalchemy.dialects.mysql import dialect

    _, engine, _, _ = charge
    order = []
    for name in ("lock_user_for_booking", "lock_reservation_for_change", "lock_payments_for_change", "get_adjustments_for_change"):
        original = getattr(booking_dao, name)
        def traced(*args, _name=name, _original=original, **kwargs):
            order.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(booking_dao, name, traced)
    with Session(engine) as db:
        commits, rollbacks, locked = [], [], []
        event.listen(db, "after_commit", lambda _: commits.append(True))
        event.listen(db, "after_rollback", lambda _: rollbacks.append(True))
        def capture(state):
            if getattr(state.statement, "_for_update_arg", None) is not None:
                locked.append(str(state.statement.compile(dialect=dialect())))
        event.listen(db, "do_orm_execute", capture)
        finance.settle_reservation_change_charge(db, acknowledgement(), 1, 7, now=NOW)
        assert commits == [True] and rollbacks == [True]
        finance.settle_reservation_change_charge(db, acknowledgement(), 1, 7, now=NOW)
        assert commits == [True]
    assert order[:4] == ["lock_user_for_booking", "lock_reservation_for_change", "lock_payments_for_change", "get_adjustments_for_change"]
    assert len(locked) == 8 and all(statement.endswith("FOR UPDATE") for statement in locked)
    assert "ORDER BY payments.payment_id" in locked[2]
    assert "ORDER BY reservation_change_adjustments.adjustment_id" in locked[3]


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_competing_settlements_use_one_transition(threaded_database, monkeypatch, status):
    engine = threaded_database
    make_charge(engine)
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, 1).status = status
        db.commit()
    barrier = Barrier(2)
    original = booking_dao.get_owned_change_adjustment

    def lookup(db, *args):
        result = original(db, *args)
        if not db.info.get("initial_lookup_done"):
            db.info["initial_lookup_done"] = True
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(booking_dao, "get_owned_change_adjustment", lookup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: settle(engine), range(2)))
    assert results[0] == results[1] and results[0].amount == 81.44
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 2
        assert db.get(ReservationChangeAdjustment, 1).status == "paid"
        assert len(db.scalars(select(ReservationChangeAdjustment)).all()) == 1
        assert len(db.scalars(select(ReservationChangeEvent)).all()) == 1
        assert db.get(Payment, 1).amount == 100


@pytest.mark.parametrize("action", ["cancelled", "amount", "revision", "ownership", "user"])
def test_authoritative_state_is_rechecked_after_waiting_for_user_lock(charge, monkeypatch, action):
    _, engine, _, _ = charge
    original = booking_dao.lock_user_for_booking
    committed = None

    def change_then_lock(db, user_id):
        nonlocal committed
        if db.info.get("simulated_competing_action"):
            return original(db, user_id)
        assert not db.in_transaction()
        with Session(engine) as other:
            other.info["simulated_competing_action"] = True
            if action == "cancelled":
                booking_service.cancel_booking(other, 1, 7)
            elif action == "amount":
                other.get(ReservationChangeAdjustment, 1).amount = Decimal("81.45")
            elif action == "revision":
                other.get(Reservation, 1).revision += 1
            elif action == "ownership":
                other.get(Reservation, 1).user_id = 8
            else:
                other.get(User, 7).status = "deleted"
            other.commit()
        committed = snapshot(engine)
        return original(db, user_id)

    monkeypatch.setattr(booking_dao, "lock_user_for_booking", change_then_lock)
    with pytest.raises(HTTPException) as error:
        settle(engine)
    assert error.value.status_code == (404 if action == "ownership" else 401 if action == "user" else 409)
    assert snapshot(engine) == committed


def test_provider_is_never_called_and_new_routes_remain_unregistered(charge, monkeypatch):
    client, engine, _, _ = charge
    def forbidden_provider(*_):
        raise AssertionError("settlement or summary attempted a provider request")
    monkeypatch.setattr(serpapi_client, "search_google_hotels", forbidden_provider)
    summary(engine)
    with Session(engine) as db:
        finance.get_owned_adjustment_detail(db, 1, 7)
    settle(engine)
    summary(engine)
    assert client.post("/bookings/1/change-confirm", json={}).status_code == 404
    assert client.post("/bookings/adjustments/1/pay", json={}).status_code == 404
    assert client.get("/bookings/1/financial-summary").status_code == 404


def test_financial_reads_cannot_autoflush_staged_records(charge):
    _, engine, _, _ = charge
    before = snapshot(engine)
    writes = []

    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().split()[0].upper() in ("INSERT", "UPDATE", "DELETE"):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as db:
            staged = User(user_id=9, email="staged@example.test", password_hash="test", status="active")
            db.add(staged)
            finance.get_owned_adjustment_detail(db, 1, 7)
            finance.get_reservation_financial_summary(db, 1, 7)
            assert staged in db.new and writes == []
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert snapshot(engine) == before


def test_one_cent_charge_remains_exact_in_summary_and_settlement(quote_app):
    _, engine, calls, _ = quote_app
    with Session(engine) as db:
        db.get(Payment, 1).payment_status = "paid"
        db.get(Payment, 1).amount = 181.43
        db.commit()
    confirm(engine, confirmation(review(engine)))
    assert summary(engine).outstanding_additional_amount == 0.01
    count = len(calls)
    result = settle(engine, acknowledgement(amount=0.010000000000001))
    assert result.amount == 0.01 and summary(engine).paid_additional_charges == 0.01
    assert summary(engine).outstanding_additional_amount == 0 and len(calls) == count


def test_settlement_invalidates_earlier_change_quote_without_provider_call(charge):
    _, engine, calls, _ = charge
    reviewed = review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")
    settle(engine)
    before = snapshot(engine)
    count = len(calls)
    with pytest.raises(HTTPException) as error:
        confirm(engine, confirmation(reviewed))
    assert error.value.status_code == 409
    assert snapshot(engine) == before and len(calls) == count


def test_failed_charge_blocks_change_until_same_record_is_settled(charge):
    _, engine, _, _ = charge
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, 1).status = "failed"
        db.commit()
    request = confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11"))
    with pytest.raises(HTTPException) as error:
        confirm(engine, request)
    assert error.value.status_code == 409
    settle(engine)
    receipt = confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")))
    assert receipt["revision"] == 3 and receipt["previous_payment_obligation"] == "181.44"
    assert receipt["adjustment"]["amount"] == "90.72"
    with Session(engine) as db:
        assert db.get(ReservationChangeAdjustment, 1).status == "paid"
        assert db.get(Payment, 1).amount == 100
