"""Internal adjustment settlement and authenticated financial reads.

Callers must supply the customer ID from get_current_user_id and a dedicated
request Session. Reconciliation is staged by the existing cancellation operation.
No provider call, external charge/refund, date change or booking Payment mutation
occurs in these helpers.
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.reservation_change_adjustment import ReservationChangeAdjustment
from app.repositories import booking_dao
from app.schemas.booking_schema import PaymentResponse
from app.schemas.reservation_change_adjustment_schema import ReservationChangeAdjustmentRecord
from app.schemas.reservation_change_payment_schema import (
    AdjustmentDetailResponse,
    AdjustmentSettlementRequest,
    AdjustmentSettlementResponse,
    ReservationFinancialSummary,
)
from app.services.booking_service import _money, _cancellation_charge_amount
from app.services.reservation_change_service import _require_active_user
from app.utilities.reservation_change_quote import _utc_now
from app.utilities.reservation_change_serialization import canonical_money


def _conflict():
    return HTTPException(status_code=409, detail="Reservation adjustment or financial state is inconsistent or unsupported")


def _amount(value, *, allow_zero=False):
    try:
        amount = Decimal(canonical_money(value))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise _conflict() from exc
    if amount < 0 or (amount == 0 and not allow_zero):
        raise _conflict()
    return amount


def _numeric(amount):
    # Aggregates can legitimately exceed one DECIMAL(10,2) record's maximum.
    # Each component is validated by _amount; retain exact Decimal sums here.
    return float(_money(amount))


def _timestamp(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _detail(adjustment, change):
    return AdjustmentDetailResponse(
        adjustment_id=adjustment.adjustment_id, change_id=change.change_id,
        reservation_id=change.reservation_id, entry_role=adjustment.entry_role,
        reconciles_adjustment_id=adjustment.reconciles_adjustment_id,
        kind=adjustment.kind, amount=_numeric(_amount(adjustment.amount)),
        status=adjustment.status, settled_at=_timestamp(adjustment.settled_at),
    )


def _owned_adjustment(db, adjustment_id, user_id):
    _require_active_user(db, user_id)
    if type(adjustment_id) is not int or adjustment_id <= 0:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    records = booking_dao.get_owned_change_adjustment(db, adjustment_id, user_id)
    if records is None:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return records


def _validate_financial_state(reservation, payments, changes, adjustments, user_id):
    """Validate persisted event/ledger relationships without inventing balances.

    A paid original Payment is immutable after the first paid change. A pending
    Payment may have been revised in place. The event chain supplies that baseline
    and the latest obligation; credits remain independent historical entries.
    """
    booking_payments = [payment for payment in payments if payment.payment_type == "booking"]
    if (
        reservation.user_id != user_id or len(booking_payments) != 1
        or type(reservation.revision) is not int or not 0 <= reservation.revision <= 4294967295
        or reservation.status not in ("confirmed", "completed", "cancelled")
        or any(payment.reservation_id != reservation.reservation_id for payment in payments)
        or (reservation.status != "cancelled" and len(payments) != 1)
    ):
        raise _conflict()
    payment = booking_payments[0]
    if payment.payment_status not in ("pending", "paid", "failed", "refunded"):
        raise _conflict()
    _amount(reservation.total_price)
    baseline = _amount(payment.amount)
    obligation = baseline
    cancelled = reservation.status == "cancelled"
    primaries = [row for row in adjustments if row.entry_role == "price_change"]
    reconciliations = [row for row in adjustments if row.entry_role == "cancellation_reconciliation"]
    if len(primaries) + len(reconciliations) != len(adjustments) or (reconciliations and not cancelled):
        raise _conflict()
    cancellation_payments = [row for row in payments if row.payment_type == "cancellation"]
    if cancelled and (
        len(payments) != 2 or len(cancellation_payments) != 1
        or payment.payment_status not in ("pending", "refunded")
        or _amount(cancellation_payments[0].amount, allow_zero=True) != _cancellation_charge_amount(reservation.total_price)
    ):
        raise HTTPException(status_code=409, detail="Financial summary requires consistent cancellation reconciliation and charge")
    by_change = {}
    for adjustment in primaries:
        by_change.setdefault(adjustment.change_id, []).append(adjustment)
    previous = None
    paid_history = False
    seen_adjustments = set()
    for change in changes:
        old_obligation = _amount(change.old_payment_obligation)
        new_obligation = _amount(change.new_payment_obligation)
        _amount(change.old_reservation_total)
        _amount(change.new_reservation_total)
        if (
            change.reservation_id != reservation.reservation_id or change.user_id != user_id
            or change.booking_payment_id != payment.payment_id or change.currency != "USD"
            or change.revision_before < 0 or change.revision_after != change.revision_before + 1
            or change.revision_after > reservation.revision
            or change.new_check_out_date <= change.new_check_in_date
            or change.old_check_out_date <= change.old_check_in_date
            or change.booking_payment_status_before not in ("pending", "paid")
        ):
            raise _conflict()
        if previous is None:
            baseline = old_obligation
        elif (
            change.revision_before < previous.revision_after
            or old_obligation != _amount(previous.new_payment_obligation)
            or change.old_room_type_id != previous.new_room_type_id
            or change.old_check_in_date != previous.new_check_in_date
            or change.old_check_out_date != previous.new_check_out_date
            or _amount(change.old_reservation_total) != _amount(previous.new_reservation_total)
        ):
            raise _conflict()
        entries = by_change.get(change.change_id, [])
        difference = new_obligation - old_obligation
        if change.booking_payment_status_before == "pending":
            if paid_history or entries:
                raise _conflict()
            baseline = new_obligation
        else:
            paid_history = True
            if payment.payment_status not in ("paid", "refunded"):
                raise _conflict()
            if len(entries) != (1 if difference else 0):
                raise _conflict()
            for adjustment in entries:
                try:
                    ReservationChangeAdjustmentRecord(
                        change_id=adjustment.change_id, entry_role=adjustment.entry_role,
                        reconciles_adjustment_id=adjustment.reconciles_adjustment_id,
                        kind=adjustment.kind, amount=adjustment.amount, status=adjustment.status,
                    )
                except ValidationError as exc:
                    raise _conflict() from exc
                if (
                    adjustment.entry_role != "price_change" or adjustment.reconciles_adjustment_id is not None
                    or adjustment.kind != ("charge" if difference > 0 else "credit")
                    or _amount(adjustment.amount) != abs(difference)
                    or (adjustment.status == "paid" and adjustment.settled_at is None)
                    or (adjustment.status != "paid" and adjustment.settled_at is not None)
                    or (adjustment.status == "voided" and not cancelled)
                    or (cancelled and adjustment.kind == "charge" and adjustment.status in ("pending", "failed"))
                    or (adjustment.kind == "charge" and adjustment.status in ("pending", "failed")
                        and change.change_id != changes[-1].change_id)
                ):
                    raise _conflict()
                seen_adjustments.add(adjustment.adjustment_id)
        previous = change
        obligation = new_obligation
    _validate_cancellation_reconciliations(primaries, reconciliations, cancelled, seen_adjustments)
    if len(seen_adjustments) != len(adjustments) or _amount(payment.amount) != baseline:
        raise _conflict()
    if previous is not None and (
        previous.new_room_type_id != reservation.room_type_id
        or previous.new_check_in_date != reservation.check_in_date
        or previous.new_check_out_date != reservation.check_out_date
        or _amount(previous.new_reservation_total) != _amount(reservation.total_price)
    ):
        raise _conflict()
    return payment, obligation


def _validate_cancellation_reconciliations(primaries, reconciliations, cancelled, seen):
    by_parent = {}
    parents = {row.adjustment_id: row for row in primaries}
    for row in reconciliations:
        parent = parents.get(row.reconciles_adjustment_id)
        try:
            ReservationChangeAdjustmentRecord(
                change_id=row.change_id, entry_role=row.entry_role, reconciles_adjustment_id=row.reconciles_adjustment_id,
                kind=row.kind, amount=row.amount, status=row.status,
            )
        except ValidationError as exc:
            raise _conflict() from exc
        if (
            not cancelled or parent is None or parent.adjustment_id == row.adjustment_id
            or row.change_id != parent.change_id or row.kind == parent.kind
            or _amount(row.amount) != _amount(parent.amount) or row.settled_at is not None
            or not ((parent.kind == "charge" and parent.status == "paid")
                    or (parent.kind == "credit" and parent.status == "recorded"))
            or row.reconciles_adjustment_id in by_parent
        ):
            raise _conflict()
        by_parent[row.reconciles_adjustment_id] = row
        seen.add(row.adjustment_id)
    for parent in primaries:
        needs_reversal = cancelled and (
            (parent.kind == "charge" and parent.status == "paid")
            or (parent.kind == "credit" and parent.status == "recorded")
        )
        if needs_reversal != (parent.adjustment_id in by_parent):
            raise HTTPException(status_code=409, detail="Financial summary requires cancellation reconciliation")


def reconcile_adjustments_for_cancellation(
    db, reservation, payments, changes, adjustments, user_id, *, now=None,
):
    """Stage approved cancellation treatment under the caller's existing locks.

    Only outstanding charges change state. Paid charges and recorded credits
    keep every historical field; linked equal/opposite recorded entries reverse
    their reservation-specific ledger effects without collecting/paying money.
    """
    if reservation.status != "confirmed":
        raise HTTPException(status_code=409, detail="Reservation cannot be reconciled again")
    _validate_financial_state(reservation, payments, changes, adjustments, user_id)
    timestamp = _utc_now(now).replace(tzinfo=None)
    for parent in adjustments:
        if parent.kind == "charge" and parent.status in ("pending", "failed"):
            parent.status = "voided"
            parent.updated_at = timestamp
        else:
            entry = ReservationChangeAdjustmentRecord(
                change_id=parent.change_id, entry_role="cancellation_reconciliation",
                reconciles_adjustment_id=parent.adjustment_id,
                kind="credit" if parent.kind == "charge" else "charge",
                amount=_amount(parent.amount), status="recorded",
            )
            booking_dao.stage_booking_record(db, ReservationChangeAdjustment(
                **entry.model_dump(), created_at=timestamp, updated_at=timestamp, settled_at=None,
            ))


def _read_financial_state(db, reservation_id, user_id):
    records = booking_dao.get_owned_reservation_for_change(db, reservation_id, user_id)
    if records is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    reservation, _, _, payments = records
    changes = booking_dao.get_reservation_change_history(db, reservation_id)
    adjustments = booking_dao.get_adjustments_for_change(db, reservation_id)
    payment, obligation = _validate_financial_state(reservation, payments, changes, adjustments, user_id)
    return reservation, payment, obligation, changes, adjustments, payments


def get_owned_adjustment_detail(db: Session, adjustment_id: int, user_id: int) -> AdjustmentDetailResponse:
    with db.no_autoflush:
        adjustment, change, reservation = _owned_adjustment(db, adjustment_id, user_id)
        _read_financial_state(db, reservation.reservation_id, user_id)
        return _detail(adjustment, change)


def get_reservation_financial_summary(db: Session, reservation_id: int, user_id: int) -> ReservationFinancialSummary:
    """Read-only stay costs and ledger buckets, with no charge/credit netting."""
    with db.no_autoflush:
        _require_active_user(db, user_id)
        reservation, payment, obligation, changes, adjustments, payments = _read_financial_state(db, reservation_id, user_id)
        changes_by_id = {change.change_id: change for change in changes}
        primaries = [row for row in adjustments if row.entry_role == "price_change"]
        reconciliations = [row for row in adjustments if row.entry_role == "cancellation_reconciliation"]
        paid = sum((_amount(row.amount) for row in primaries if row.kind == "charge" and row.status == "paid"), Decimal(0))
        pending = sum((_amount(row.amount) for row in primaries if row.kind == "charge" and row.status == "pending"), Decimal(0))
        failed = sum((_amount(row.amount) for row in primaries if row.kind == "charge" and row.status == "failed"), Decimal(0))
        credits = sum((_amount(row.amount) for row in primaries if row.kind == "credit" and row.status == "recorded"), Decimal(0))
        voided = sum((_amount(row.amount) for row in primaries if row.kind == "charge" and row.status == "voided"), Decimal(0))
        reversal_credits = sum((_amount(row.amount) for row in reconciliations if row.kind == "credit"), Decimal(0))
        reversal_debits = sum((_amount(row.amount) for row in reconciliations if row.kind == "charge"), Decimal(0))
        cancellation = next((row for row in payments if row.payment_type == "cancellation"), None)
        cancellation_result = booking_dao.payment_result(cancellation) if cancellation is not None else None
        if cancellation_result is not None:
            cancellation_result["amount"] = _numeric(_amount(cancellation.amount, allow_zero=True))
        original_payment = booking_dao.payment_result(payment)
        original_payment["amount"] = _numeric(_amount(payment.amount))
        return ReservationFinancialSummary(
            reservation_id=reservation.reservation_id, reservation_revision=reservation.revision,
            reservation_status=reservation.status, latest_change_id=changes[-1].change_id if changes else None,
            current_reservation_total=_numeric(_amount(reservation.total_price)),
            current_booking_obligation=_numeric(obligation),
            original_booking_payment=PaymentResponse(**original_payment),
            paid_additional_charges=_numeric(paid), pending_additional_charges=_numeric(pending),
            failed_additional_charges=_numeric(failed), recorded_internal_credits=_numeric(credits),
            outstanding_additional_amount=_numeric(pending + failed),
            adjustments=[_detail(row, changes_by_id[row.change_id]) for row in primaries],
            voided_additional_charges=_numeric(voided),
            cancellation_reconciliations=[_detail(row, changes_by_id[row.change_id]) for row in reconciliations],
            reconciliation_credits=_numeric(reversal_credits), reconciliation_debits=_numeric(reversal_debits),
            cancellation_payment=PaymentResponse(**cancellation_result) if cancellation_result is not None else None,
            outstanding_cancellation_amount=_numeric(_amount(cancellation.amount, allow_zero=True))
            if cancellation is not None and cancellation.payment_status in ("pending", "failed") else 0,
            outstanding_booking_amount=_numeric(_amount(payment.amount))
            if reservation.status == "confirmed" and payment.payment_status == "pending" else 0,
        )


def settle_reservation_change_charge(
    db: Session, request: AdjustmentSettlementRequest, adjustment_id: int, user_id: int,
    *, now: datetime | None = None,
) -> AdjustmentSettlementResponse:
    """Mark the existing internal charge paid once, preserving payment/history.

    New transitions require the current revision and cent-equivalent amount.
    Already-paid retries allow an older revision with the identical amount since
    they authorize no write; future revision acknowledgements remain conflicts.
    """
    try:
        request = AdjustmentSettlementRequest.model_validate(request.model_dump())
        with db.no_autoflush:
            _, _, owned = _owned_adjustment(db, adjustment_id, user_id)
            reservation_id = owned.reservation_id
        db.rollback()
        _require_active_user(db, user_id, lock=True)
        reservation = booking_dao.lock_reservation_for_change(db, reservation_id, user_id)
        if reservation is None:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        payments = booking_dao.lock_payments_for_change(db, reservation_id)
        adjustments = booking_dao.get_adjustments_for_change(db, reservation_id, lock=True)
        owned = booking_dao.get_owned_change_adjustment(db, adjustment_id, user_id)
        if owned is None or owned[2].reservation_id != reservation_id:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        adjustment, change, _ = owned
        if reservation.status == "cancelled":
            raise HTTPException(status_code=409, detail="Cancelled reservations cannot settle additional charges")
        changes = booking_dao.get_reservation_change_history(db, reservation_id)
        payment, _ = _validate_financial_state(reservation, payments, changes, adjustments, user_id)
        if (
            payment.payment_status != "paid" or adjustment.kind != "charge"
            or adjustment.entry_role != "price_change" or adjustment.status not in ("pending", "failed", "paid")
            or Decimal(canonical_money(request.accepted_amount)) != _amount(adjustment.amount)
            or request.reservation_revision > reservation.revision
        ):
            raise _conflict()
        if adjustment.status == "paid":
            result = AdjustmentSettlementResponse(**_detail(adjustment, change).model_dump())
            db.rollback()
            return result
        if (
            reservation.status != "confirmed" or request.reservation_revision != reservation.revision
            or reservation.revision >= 4294967295
        ):
            raise HTTPException(status_code=409, detail="Adjustment review is stale or reservation cannot be paid")
        timestamp = _utc_now(now).replace(tzinfo=None)
        adjustment.status = "paid"
        adjustment.settled_at = timestamp
        adjustment.updated_at = timestamp
        reservation.revision += 1
        result = AdjustmentSettlementResponse(**_detail(adjustment, change).model_dump())
        db.commit()
        return result
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Invalid adjustment payment acknowledgement") from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to record internal adjustment payment") from exc
