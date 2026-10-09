"""Cancellation ledger tests using isolated SQLite and mocked hotel pricing.

Concurrency tests simulate row-lock waits with mutexes around real Sessions.
They do not verify MySQL/InnoDB contention or access development records.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Payment, Reservation, ReservationChangeAdjustment, ReservationChangeEvent, User
from app.repositories import booking_dao
from app.services import booking_service, reservation_change_payment_service as finance
from app.utilities import serpapi_client

from test_reservation_change_confirmation import confirm, confirmation, review, snapshot, threaded_database
from test_reservation_change_payment import acknowledgement, make_charge, settle, summary
from test_reservation_change_quotes import NOW, headers, quote_app


def cancel(engine, user_id=7, reservation_id=1):
    with Session(engine) as db:
        return booking_service.cancel_booking(db, reservation_id, user_id)


def rejected_cancellation(engine, *, expected=409, **kwargs):
    before = snapshot(engine)
    with pytest.raises(HTTPException) as error:
        cancel(engine, **kwargs)
    assert error.value.status_code == expected
    assert snapshot(engine) == before


def set_original_payment(engine, status, amount=None):
    with Session(engine) as db:
        payment = db.get(Payment, 1)
        payment.payment_status = status
        if amount is not None:
            payment.amount = amount
        db.commit()


@pytest.mark.parametrize("status", ["pending", "paid"])
def test_ordinary_cancellation_keeps_public_contract_and_duplicate_rejection(quote_app, status):
    client, engine, calls, _ = quote_app
    set_original_payment(engine, status)
    response = client.post("/bookings/cancel-booking/1", headers=headers())
    assert response.status_code == 200
    assert response.json() == {
        "reservation_id": 1, "status": "cancelled", "booking_payment_id": 1,
        "booking_payment_status": "pending" if status == "pending" else "refunded",
        "cancellation_payment_id": 2, "cancellation_amount": 42.0,
        "cancellation_payment_status": "pending",
    }
    rejected_cancellation(engine)
    value = summary(engine)
    assert value.original_booking_payment.amount == 226.8
    assert value.cancellation_payment.amount == value.outstanding_cancellation_amount == 42
    assert value.outstanding_additional_amount == value.outstanding_booking_amount == 0
    assert value.cancellation_reconciliations == [] and value.adjustments == [] and calls == []
    with Session(engine) as db:
        assert db.get(Reservation, 1).revision == 1
        assert len(db.scalars(select(Payment)).all()) == 2


@pytest.mark.parametrize("user_id,reservation_id,expected", [(8, 1, 404), (7, 999, 404)])
def test_nonowned_and_missing_cancellation_do_not_disclose_records(quote_app, user_id, reservation_id, expected):
    rejected_cancellation(quote_app[1], expected=expected, user_id=user_id, reservation_id=reservation_id)


def test_inactive_owner_and_partner_cannot_cancel(quote_app):
    client, engine, _, _ = quote_app
    assert client.post("/bookings/cancel-booking/1", headers=headers(7, "partner")).status_code == 401
    with Session(engine) as db:
        db.get(User, 7).status = "deleted"
        db.commit()
    rejected_cancellation(engine, expected=401)


@pytest.mark.parametrize("nights", [1, 2, 3, 4])
def test_unpaid_revised_obligation_cancellation_uses_latest_total(quote_app, nights):
    _, engine, calls, _ = quote_app
    revised = confirm(engine, confirmation(review(engine, check_out_date=f"2026-11-{4 + nights:02}")))
    before = snapshot(engine)
    count = len(calls)
    response = cancel(engine)
    expected = booking_service._money(Decimal(revised["reservation_total"]) * Decimal("0.20"))
    assert Decimal(str(response.cancellation_amount)) == expected
    after = snapshot(engine)
    assert after["reservation_change_events"] == before["reservation_change_events"]
    assert after["reservation_change_adjustments"] == [] and len(calls) == count
    assert len(after["payments"]) == 2
    assert after["payments"][0] == before["payments"][0]
    assert after["reservations"][0]["revision"] == 2
    value = summary(engine)
    assert value.current_reservation_total == float(revised["reservation_total"])
    assert value.current_booking_obligation == value.original_booking_payment.amount == float(revised["payment_obligation"])
    assert value.original_booking_payment.payment_status == "pending"
    assert value.outstanding_booking_amount == value.outstanding_additional_amount == 0
    assert value.outstanding_cancellation_amount == float(expected)


def test_multiple_unpaid_changes_preserve_all_history_and_one_cancellation_charge(quote_app):
    _, engine, _, _ = quote_app
    confirm(engine, confirmation(review(engine)))
    confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-12")))
    before = snapshot(engine)
    assert cancel(engine).cancellation_amount == 67.2
    rejected_cancellation(engine)
    after = snapshot(engine)
    assert after["reservation_change_events"] == before["reservation_change_events"]
    assert len(after["reservation_change_events"]) == 2 and after["reservation_change_adjustments"] == []
    assert after["payments"][0]["amount"] == 362.88 and len(after["payments"]) == 2
    assert summary(engine).current_booking_obligation == 362.88


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_outstanding_charges_are_voided_and_never_collectible(quote_app, status):
    _, engine, calls, _ = quote_app
    make_charge(engine)
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, 1).status = status
        db.commit()
    before = snapshot(engine)
    count = len(calls)
    response = cancel(engine)
    after = snapshot(engine)
    assert response.cancellation_amount == 33.6 and response.booking_payment_status == "refunded"
    parent = after["reservation_change_adjustments"][0]
    expected = {**before["reservation_change_adjustments"][0], "status": "voided", "updated_at": parent["updated_at"]}
    assert parent == expected and parent["settled_at"] is None
    assert after["reservation_change_events"] == before["reservation_change_events"]
    assert len(after["reservation_change_adjustments"]) == 1
    assert after["payments"][0]["amount"] == 100
    value = summary(engine)
    assert value.voided_additional_charges == 81.44
    assert value.pending_additional_charges == value.failed_additional_charges == value.outstanding_additional_amount == 0
    assert value.cancellation_reconciliations == [] and value.outstanding_cancellation_amount == 33.6
    with pytest.raises(HTTPException) as error:
        settle(engine)
    assert error.value.status_code == 409 and len(calls) == count
    assert snapshot(engine) == after


@pytest.mark.parametrize("kind", ["charge", "credit"])
def test_paid_charges_and_recorded_credits_receive_equal_opposite_recorded_entries(quote_app, kind):
    _, engine, calls, _ = quote_app
    if kind == "charge":
        make_charge(engine)
        settle(engine)
        amount = Decimal("81.44")
    else:
        set_original_payment(engine, "paid")
        confirm(engine, confirmation(review(engine)))
        amount = Decimal("45.36")
    before = snapshot(engine)
    count = len(calls)
    response = cancel(engine)
    assert response.cancellation_amount == 33.6
    after = snapshot(engine)
    assert after["reservation_change_events"] == before["reservation_change_events"]
    assert after["reservation_change_adjustments"][0] == before["reservation_change_adjustments"][0]
    assert len(after["reservation_change_adjustments"]) == 2
    reversal = after["reservation_change_adjustments"][1]
    assert reversal["entry_role"] == "cancellation_reconciliation" and reversal["reconciles_adjustment_id"] == 1
    assert reversal["change_id"] == 1 and reversal["kind"] == ("credit" if kind == "charge" else "charge")
    assert reversal["status"] == "recorded" and reversal["amount"] == amount and reversal["settled_at"] is None
    assert reversal["created_at"] == reversal["updated_at"]
    assert after["payments"][0]["amount"] == before["payments"][0]["amount"]
    value = summary(engine)
    assert value.paid_additional_charges == (81.44 if kind == "charge" else 0)
    assert value.recorded_internal_credits == (45.36 if kind == "credit" else 0)
    assert value.reconciliation_credits == (81.44 if kind == "charge" else 0)
    assert value.reconciliation_debits == (45.36 if kind == "credit" else 0)
    assert len(value.adjustments) == len(value.cancellation_reconciliations) == 1
    assert value.cancellation_reconciliations[0].reconciles_adjustment_id == 1
    assert value.outstanding_additional_amount == 0 and value.outstanding_cancellation_amount == 33.6
    rejected_cancellation(engine)
    with pytest.raises(HTTPException) as error:
        settle(engine, acknowledgement(amount=amount))
    assert error.value.status_code == 409
    assert snapshot(engine) == after and len(calls) == count


def test_multiple_sequential_changes_reconcile_each_parent_without_netting(quote_app):
    _, engine, _, _ = quote_app
    set_original_payment(engine, "paid")
    confirm(engine, confirmation(review(engine)))  # recorded credit 45.36
    second = confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")))
    settle(engine, acknowledgement(amount=90.72, revision=2), adjustment_id=second["adjustment"]["adjustment_id"])
    confirm(engine, confirmation(review(engine, check_in_date="2026-11-15", check_out_date="2026-11-19")))
    before = snapshot(engine)
    assert cancel(engine).cancellation_amount == 67.2
    after = snapshot(engine)
    assert after["reservation_change_events"] == before["reservation_change_events"]
    assert after["reservation_change_adjustments"][:2] == before["reservation_change_adjustments"][:2]
    assert after["reservation_change_adjustments"][2]["status"] == "voided"
    assert len(after["reservation_change_adjustments"]) == 5
    value = summary(engine)
    assert value.current_booking_obligation == 362.88 and value.current_reservation_total == 336
    assert value.original_booking_payment.amount == 226.8 and value.original_booking_payment.payment_status == "refunded"
    assert value.paid_additional_charges == value.voided_additional_charges == 90.72
    assert value.recorded_internal_credits == value.reconciliation_debits == 45.36
    assert value.reconciliation_credits == 90.72
    assert value.outstanding_additional_amount == value.outstanding_booking_amount == 0
    assert value.outstanding_cancellation_amount == 67.2
    assert len(value.cancellation_reconciliations) == 2 and value.reservation_revision == 5
    assert len(after["payments"]) == 2


@pytest.mark.parametrize("failure", ["first_reversal", "second_reversal", "after_void", "cancellation_payment", "commit", "deadlock"])
def test_reconciliation_failure_rolls_back_every_candidate_and_retry_succeeds(quote_app, monkeypatch, failure):
    _, engine, _, _ = quote_app
    set_original_payment(engine, "paid")
    confirm(engine, confirmation(review(engine)))
    second = confirm(engine, confirmation(review(engine, check_in_date="2026-11-08", check_out_date="2026-11-11")))
    settle(engine, acknowledgement(amount=90.72, revision=2), adjustment_id=second["adjustment"]["adjustment_id"])
    confirm(engine, confirmation(review(engine, check_in_date="2026-11-15", check_out_date="2026-11-19")))
    before = snapshot(engine)
    with monkeypatch.context() as patch, Session(engine) as db:
        original_stage = booking_dao.stage_booking_record
        count = 0

        def staged(session, row):
            nonlocal count
            result = original_stage(session, row)
            if isinstance(row, ReservationChangeAdjustment) and row.entry_role == "cancellation_reconciliation":
                count += 1
                if (failure == "first_reversal" and count == 1) or (failure == "second_reversal" and count == 2):
                    raise RuntimeError("injected after reconciliation insert")
            return result

        patch.setattr(booking_dao, "stage_booking_record", staged)
        if failure == "after_void":
            def after_flush(session, *_):
                if any(row.status == "voided" for row in session.identity_map.values() if isinstance(row, ReservationChangeAdjustment)):
                    raise RuntimeError("injected after void UPDATE")
            event.listen(db, "after_flush", after_flush)
        elif failure == "cancellation_payment":
            def after_flush(session, *_):
                if any(row.payment_type == "cancellation" for row in session.new if isinstance(row, Payment)):
                    raise RuntimeError("injected cancellation payment insert failure")
            event.listen(db, "after_flush", after_flush)
        elif failure == "commit":
            patch.setattr(db, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("commit failure")))
        elif failure == "deadlock":
            patch.setattr(booking_dao, "get_adjustments_for_change", lambda *_args, **_kwargs: (_ for _ in ()).throw(OperationalError("lock", {}, Exception("deadlock"))))
        with pytest.raises(HTTPException) as error:
            booking_service.cancel_booking(db, 1, 7)
        assert error.value.status_code == 500 and not db.in_transaction()
    assert snapshot(engine) == before
    assert cancel(engine).status == "cancelled"
    assert summary(engine).outstanding_additional_amount == 0


@pytest.mark.parametrize("field,value", [("user_id", 8), ("booking_payment_id", 999), ("new_reservation_total", Decimal("168.01"))])
def test_inconsistent_history_cannot_be_cancelled(quote_app, field, value):
    _, engine, _, _ = quote_app
    make_charge(engine)
    with Session(engine) as db:
        setattr(db.get(ReservationChangeEvent, 1), field, value)
        db.commit()
    rejected_cancellation(engine)


def test_duplicate_compensation_is_rejected_by_actual_database_uniqueness(quote_app):
    _, engine, _, _ = quote_app
    make_charge(engine)
    settle(engine)
    cancel(engine)
    before = snapshot(engine)
    with Session(engine) as db, pytest.raises(IntegrityError):
        db.add(ReservationChangeAdjustment(change_id=1, entry_role="cancellation_reconciliation",
                reconciles_adjustment_id=1, kind="credit", amount=Decimal("81.44"), status="recorded"))
        db.commit()
    assert snapshot(engine) == before
    with Session(engine) as db:
        records = booking_dao.get_owned_reservation_for_change(db, 1, 7)
        changes = booking_dao.get_reservation_change_history(db, 1)
        adjustments = booking_dao.get_adjustments_for_change(db, 1)
        with pytest.raises(HTTPException) as error:
            finance.reconcile_adjustments_for_cancellation(db, records[0], records[3], changes, adjustments, 7)
        assert error.value.status_code == 409 and not db.new and not db.dirty
    assert snapshot(engine) == before


def foreign_history(engine):
    """Another customer's ledger fixture, with valid same-event ownership links."""
    with Session(engine) as db:
        template = db.get(ReservationChangeEvent, 1)
        values = {column.name: getattr(template, column.name) for column in template.__table__.columns if column.name != "change_id"}
        values.update(user_id=8, reservation_id=2, booking_payment_id=2,
                      old_room_type_id=2, new_room_type_id=2, quote_jti=str(uuid4()))
        db.add(Reservation(reservation_id=2, user_id=8, room_type_id=2, total_price=168, status="confirmed",
                           check_in_date=date(2026, 11, 4), check_out_date=date(2026, 11, 6), revision=1))
        db.add(Payment(payment_id=2, reservation_id=2, amount=100, payment_type="booking", payment_status="paid"))
        db.flush()
        change = ReservationChangeEvent(**values)
        db.add(change)
        db.flush()
        db.add(ReservationChangeAdjustment(change_id=change.change_id, kind="charge", amount=Decimal("81.44"), status="pending"))
        db.commit()
        return change.change_id


def test_cancellation_does_not_reconcile_another_reservations_adjustments(quote_app):
    _, engine, _, _ = quote_app
    make_charge(engine)
    other_change_id = foreign_history(engine)
    before = snapshot(engine)
    cancel(engine)
    after = snapshot(engine)
    assert after["reservations"][1] == before["reservations"][1]
    assert after["payments"][1] == before["payments"][1]
    assert after["reservation_change_adjustments"][1] == before["reservation_change_adjustments"][1]
    assert after["reservation_change_adjustments"][1]["change_id"] == other_change_id


def test_composite_foreign_key_rejects_cross_reservation_reconciliation(quote_app):
    _, engine, _, _ = quote_app
    make_charge(engine)
    other_change_id = foreign_history(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    before = snapshot(engine)
    with Session(engine) as db, pytest.raises(IntegrityError):
        db.add(ReservationChangeAdjustment(change_id=other_change_id, entry_role="cancellation_reconciliation",
                reconciles_adjustment_id=1, kind="credit", amount=Decimal("81.44"), status="recorded"))
        db.commit()
    assert snapshot(engine) == before


@pytest.mark.parametrize("field,value", [("amount", Decimal("81.43")), ("kind", "charge"), ("reconciles_adjustment_id", 999), ("settled_at", NOW.replace(tzinfo=None))])
def test_summary_rejects_contradictory_reconciliation(quote_app, field, value):
    _, engine, _, _ = quote_app
    make_charge(engine)
    settle(engine)
    cancel(engine)
    with Session(engine) as db:
        setattr(db.get(ReservationChangeAdjustment, 2), field, value)
        db.commit()
    before = snapshot(engine)
    with pytest.raises(HTTPException) as error:
        summary(engine)
    assert error.value.status_code == 409 and snapshot(engine) == before


def test_unconsumed_change_quote_is_invalid_after_cancellation_without_provider(quote_app):
    _, engine, calls, _ = quote_app
    reviewed = review(engine)
    cancel(engine)
    count = len(calls)
    before = snapshot(engine)
    with pytest.raises(HTTPException) as error:
        confirm(engine, confirmation(reviewed))
    assert error.value.status_code == 409 and len(calls) == count and snapshot(engine) == before


def test_existing_committed_change_receipt_remains_immutable_after_cancellation(quote_app):
    _, engine, calls, _ = quote_app
    set_original_payment(engine, "paid")
    reviewed = review(engine)
    request = confirmation(reviewed)
    receipt = confirm(engine, request)
    cancel(engine)
    count = len(calls)
    before = snapshot(engine)
    assert confirm(engine, request) == receipt
    assert snapshot(engine) == before and len(calls) == count


def synchronize_user_wait(monkeypatch):
    barrier = Barrier(2)
    original = booking_dao.lock_user_for_booking
    def lock(db, user_id):
        assert not db.in_transaction()
        barrier.wait(timeout=10)
        return original(db, user_id)
    monkeypatch.setattr(booking_dao, "lock_user_for_booking", lock)


@pytest.mark.parametrize("status", ["pending", "failed"])
def test_cancellation_races_with_adjustment_settlement(threaded_database, monkeypatch, status):
    engine = threaded_database
    make_charge(engine)
    with Session(engine) as db:
        db.get(ReservationChangeAdjustment, 1).status = status
        db.commit()
    synchronize_user_wait(monkeypatch)
    def attempt(pay):
        try:
            return settle(engine) if pay else cancel(engine)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        payment, cancellation = list(pool.map(attempt, [True, False]))
    assert cancellation.status == "cancelled"
    value = summary(engine)
    assert value.outstanding_additional_amount == 0 and value.outstanding_cancellation_amount == 33.6
    with Session(engine) as db:
        parent = db.get(ReservationChangeAdjustment, 1)
        rows = db.scalars(select(ReservationChangeAdjustment)).all()
        if payment == 409:
            assert parent.status == "voided" and len(rows) == 1 and value.reservation_revision == 2
        else:
            assert payment.status == parent.status == "paid" and len(rows) == 2 and value.reservation_revision == 3
            assert rows[1].kind == "credit" and rows[1].status == "recorded"
        assert len(db.scalars(select(Payment)).all()) == 2


def test_cancellation_races_with_change_confirmation(threaded_database, monkeypatch):
    engine = threaded_database
    set_original_payment(engine, "paid")
    reviewed = review(engine)
    synchronize_user_wait(monkeypatch)
    def attempt(change):
        try:
            return confirm(engine, confirmation(reviewed)) if change else cancel(engine)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        change, cancellation = list(pool.map(attempt, [True, False]))
    assert cancellation.status == "cancelled"
    value = summary(engine)
    if change == 409:
        assert cancellation.cancellation_amount == 42 and value.reservation_revision == 1
        assert value.adjustments == [] and value.cancellation_reconciliations == []
    else:
        assert cancellation.cancellation_amount == 33.6 and value.reservation_revision == 2
        assert value.recorded_internal_credits == value.reconciliation_debits == 45.36
    assert value.outstanding_additional_amount == 0


def test_duplicate_concurrent_cancellation_has_one_fee_and_one_reconciliation(threaded_database, monkeypatch):
    engine = threaded_database
    make_charge(engine)
    settle(engine)
    synchronize_user_wait(monkeypatch)
    def attempt(_):
        try:
            return cancel(engine)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(value == 409 for value in results) == 1
    value = summary(engine)
    assert value.reservation_revision == 3 and len(value.cancellation_reconciliations) == 1
    with Session(engine) as db:
        assert len(db.scalars(select(Payment)).all()) == 2


def test_cancellation_races_with_original_booking_payment(threaded_database, monkeypatch):
    engine = threaded_database
    barrier, mutex = Barrier(2), Lock()
    originals = {name: getattr(booking_dao, name) for name in ("get_reservation_for_cancellation", "lock_owned_reservation")}
    def acquire(db, *args, _name):
        barrier.wait(timeout=10)
        mutex.acquire()
        db.info["simulated_reservation_lock"] = True
        return originals[_name](db, *args)
    for name in originals:
        monkeypatch.setattr(booking_dao, name, lambda db, *args, _name=name: acquire(db, *args, _name=_name))
    def release(db, *_):
        if db.info.pop("simulated_reservation_lock", False):
            mutex.release()
    event.listen(Session, "after_commit", release)
    event.listen(Session, "after_rollback", release)
    def attempt(pay):
        try:
            if pay:
                with Session(engine) as db:
                    return booking_service.pay_booking_payment(db, 1, 7)
            return cancel(engine)
        except HTTPException as exc:
            return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            payment, cancellation = list(pool.map(attempt, [True, False]))
    finally:
        event.remove(Session, "after_commit", release)
        event.remove(Session, "after_rollback", release)
    assert cancellation.cancellation_amount == 42
    value = summary(engine)
    assert value.reservation_revision == (1 if payment == 409 else 2)
    assert value.original_booking_payment.payment_status == ("pending" if payment == 409 else "refunded")
    assert value.outstanding_booking_amount == value.outstanding_additional_amount == 0


def test_cancellation_lock_order_refresh_single_commit_and_no_provider(quote_app, monkeypatch):
    from sqlalchemy.dialects.mysql import dialect
    _, engine, _, _ = quote_app
    make_charge(engine)
    def forbidden(*_):
        raise AssertionError("cancellation called SerpApi")
    monkeypatch.setattr(serpapi_client, "search_google_hotels", forbidden)
    with Session(engine) as db:
        locked, commits, rollbacks = [], [], []
        db.get(Reservation, 1)  # earlier identity-map/read transaction
        def capture(state):
            if getattr(state.statement, "_for_update_arg", None) is not None:
                locked.append(str(state.statement.compile(dialect=dialect())))
        event.listen(db, "do_orm_execute", capture)
        event.listen(db, "after_commit", lambda _: commits.append(True))
        event.listen(db, "after_rollback", lambda _: rollbacks.append(True))
        booking_service.cancel_booking(db, 1, 7)
        assert commits == [True] and rollbacks == [True]
    assert len(locked) == 4 and all(sql.endswith("FOR UPDATE") for sql in locked)
    assert "users.user_id" in locked[0] and "reservations.reservation_id" in locked[1]
    assert "ORDER BY payments.payment_id" in locked[2]
    assert "ORDER BY reservation_change_adjustments.adjustment_id" in locked[3]
    assert summary(engine).outstanding_additional_amount == 0


@pytest.mark.parametrize("total,fee", [(100.01, 20.0), (123.45, 24.69), (0.01, 0.0)])
def test_cancellation_fee_uses_existing_twenty_percent_at_database_cent_precision(quote_app, total, fee):
    _, engine, _, _ = quote_app
    with Session(engine) as db:
        db.get(Reservation, 1).total_price = total
        db.commit()
    assert cancel(engine).cancellation_amount == fee
    value = summary(engine)
    assert value.cancellation_payment.amount == value.outstanding_cancellation_amount == fee
    assert value.outstanding_additional_amount == 0


@pytest.mark.parametrize("case", ["missing_reversal", "extra_void_reversal", "wrong_fee", "missing_fee", "paid_to_voided"])
def test_cancelled_summary_rejects_incomplete_or_misleading_financial_state(quote_app, case):
    _, engine, _, _ = quote_app
    make_charge(engine)
    if case != "extra_void_reversal":
        settle(engine)
    cancel(engine)
    with Session(engine) as db:
        if case == "missing_reversal":
            db.delete(db.get(ReservationChangeAdjustment, 2))
        elif case == "extra_void_reversal":
            db.add(ReservationChangeAdjustment(change_id=1, entry_role="cancellation_reconciliation",
                    reconciles_adjustment_id=1, kind="credit", amount=Decimal("81.44"), status="recorded"))
        elif case == "wrong_fee":
            db.get(Payment, 2).amount = 33.59
        elif case == "missing_fee":
            db.delete(db.get(Payment, 2))
        else:
            db.get(ReservationChangeAdjustment, 1).status = "voided"
        db.commit()
    before = snapshot(engine)
    with pytest.raises(HTTPException) as error:
        summary(engine)
    assert error.value.status_code == 409 and snapshot(engine) == before


@pytest.mark.parametrize("paid_adjustment", [False, True])
def test_paid_price_increase_reconciles_tax_inclusive_delta_and_separate_revised_fee(quote_app, paid_adjustment):
    _, engine, _, _ = quote_app
    set_original_payment(engine, "paid")  # stored subtotal 210, paid obligation 226.80
    changed = confirm(engine, confirmation(review(engine, check_out_date="2026-11-07")))
    assert changed["reservation_total"] == "252.00" and changed["payment_obligation"] == "272.16"
    assert changed["adjustment"]["amount"] == "45.36"
    if paid_adjustment:
        settle(engine, acknowledgement(amount=45.36))
    before = snapshot(engine)
    assert cancel(engine).cancellation_amount == 50.40
    value = summary(engine)
    assert value.current_reservation_total == 252 and value.current_booking_obligation == 272.16
    assert value.original_booking_payment.amount == 226.8
    assert value.outstanding_cancellation_amount == 50.4 and value.outstanding_additional_amount == 0
    assert value.paid_additional_charges == value.reconciliation_credits == (45.36 if paid_adjustment else 0)
    assert value.voided_additional_charges == (0 if paid_adjustment else 45.36)
    assert snapshot(engine)["reservation_change_events"] == before["reservation_change_events"]
