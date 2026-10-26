"""Read the supported pre-change financial state without inventing a ledger.

Revision 0 is an initial-state API convention, NOT a persisted revision or proof
of freshness. Null latest_change_id, empty adjustment/reconciliation histories
and zero related aggregates describe only this application's pre-change records;
they do not verify unknown external or historical transactions. This endpoint
cannot authorize confirmation, settlement or other revision-dependent mutations.
Those require separately approved persistence, coordinated writer revisions and
locks, real history, accounting rules, and idempotency/engine verification.

Amounts come from validated stored records, never today's quote, tax or fee
policy. Paid/refunded markers do not prove an external transfer. Outstanding
amounts classify recorded pending/failed obligations only; they neither collect
money nor grant payment/retry permission. A cancelled original is never payable
through this summary, even if its original Payment still says pending.
"""

from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.repositories import reservation_financial_summary_dao as summary_dao
from app.schemas.booking_schema import PaymentResponse
from app.schemas.reservation_change_payment_schema import ReservationFinancialSummary

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_MAX_MONEY = Decimal("99999999.99")
_MAX_ID = 9007199254740991
_UNPAID = ("pending", "failed")


def _positive_id(value: object) -> bool:
    return type(value) is int and 0 < value <= _MAX_ID


def _money(value: object, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Invalid monetary value")
    amount = Decimal(str(value))
    if (not amount.is_finite() or amount < 0 or amount > _MAX_MONEY
            or (not allow_zero and amount == 0)
            or amount != amount.quantize(_CENT)):
        raise ValueError("Unsupported monetary value")
    return _ZERO if amount == 0 else amount.quantize(_CENT)


def _payment(row, reservation_id: int) -> tuple[PaymentResponse, Decimal]:
    if (not _positive_id(row["payment_id"])
            or type(row["payment_reservation_id"]) is not int
            or row["payment_reservation_id"] != reservation_id
            or row["payment_type"] not in ("booking", "cancellation")
            or row["payment_status"] not in ("pending", "paid", "failed", "refunded")):
        raise ValueError("Unverifiable payment identity or state")
    amount = _money(row["amount"], allow_zero=row["payment_type"] == "cancellation")
    return PaymentResponse(
        payment_id=row["payment_id"], reservation_id=reservation_id,
        amount=float(amount), payment_type=row["payment_type"],
        payment_status=row["payment_status"],
    ), amount


def get_financial_summary(
    db: Session, reservation_id: int, user_id: int,
) -> ReservationFinancialSummary:
    """Project one owner's baseline accounting state without writes or repricing."""
    if not _positive_id(reservation_id):
        raise HTTPException(status_code=422, detail="Invalid reservation ID")
    try:
        rows = summary_dao.get_owned_financial_rows(db, reservation_id, user_id)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Financial summary is temporarily unavailable") from None
    except LookupError:
        # SQLAlchemy Enum decoding also rejects malformed persisted enum values.
        raise HTTPException(status_code=409, detail="Reservation financial state cannot be verified") from None
    if not rows or any(
        row["reservation_id"] != reservation_id or row["user_id"] != user_id for row in rows
    ):
        raise HTTPException(status_code=404, detail="Reservation not found")
    try:
        first = rows[0]
        status = first["reservation_status"]
        if status not in ("confirmed", "completed", "cancelled") or len(rows) > 2:
            raise ValueError("Unsupported reservation history")
        total = _money(first["total_price"])
        payments = {}
        identities = set()
        for row in rows:
            if (row["reservation_status"] != status or _money(row["total_price"]) != total
                    or not _positive_id(row["reservation_id"]) or not _positive_id(row["user_id"])):
                raise ValueError("Inconsistent reservation projection")
            payment, amount = _payment(row, reservation_id)
            if payment.payment_type in payments or payment.payment_id in identities:
                raise ValueError("Ambiguous payment history")
            payments[payment.payment_type] = (payment, amount)
            identities.add(payment.payment_id)
        if "booking" not in payments:
            raise ValueError("Missing original payment")
        original, obligation = payments["booking"]
        cancellation, cancellation_amount = payments.get("cancellation", (None, _ZERO))
        if status == "cancelled":
            if cancellation is None or original.payment_status not in ("pending", "refunded"):
                raise ValueError("Incomplete cancellation accounting")
        elif cancellation is not None or original.payment_status == "refunded":
            raise ValueError("Cancellation accounting on an active/completed reservation")
        outstanding_booking = (
            obligation if status != "cancelled" and original.payment_status in _UNPAID else _ZERO
        )
        outstanding_cancellation = (
            cancellation_amount if cancellation is not None and cancellation.payment_status in _UNPAID else _ZERO
        )
        return ReservationFinancialSummary(
            reservation_id=reservation_id, reservation_revision=0, reservation_status=status,
            currency="USD", latest_change_id=None,
            current_reservation_total=float(total), current_booking_obligation=float(obligation),
            original_booking_payment=original,
            paid_additional_charges=0.0, pending_additional_charges=0.0,
            failed_additional_charges=0.0, recorded_internal_credits=0.0,
            outstanding_additional_amount=0.0, adjustments=[], voided_additional_charges=0.0,
            cancellation_reconciliations=[], reconciliation_credits=0.0, reconciliation_debits=0.0,
            cancellation_payment=cancellation,
            outstanding_cancellation_amount=float(outstanding_cancellation),
            outstanding_booking_amount=float(outstanding_booking),
        )
    except (ValueError, TypeError, KeyError, InvalidOperation, ValidationError):
        raise HTTPException(status_code=409, detail="Reservation financial state cannot be verified") from None
