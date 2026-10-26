"""Owner-scoped financial projections; no guest data, autoflush or write locks."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.reservation import Reservation


def get_owned_financial_rows(db: Session, reservation_id: int, user_id: int):
    """Read one reservation and every associated Payment in a single SELECT.

    The outer join exposes missing original payments for fail-closed validation.
    Returning projections avoids modifying ORM objects or loading guest contacts.
    No nonexistent revision or adjustment table is queried.
    """
    statement = (
        select(
            Reservation.reservation_id,
            Reservation.user_id,
            Reservation.status.label("reservation_status"),
            Reservation.total_price,
            Payment.payment_id,
            Payment.reservation_id.label("payment_reservation_id"),
            Payment.amount,
            Payment.payment_type,
            Payment.payment_status,
        )
        .select_from(Reservation)
        .outerjoin(Payment, Payment.reservation_id == Reservation.reservation_id)
        .where(
            Reservation.reservation_id == reservation_id,
            Reservation.user_id == user_id,
        )
        .order_by(Payment.payment_id)
    )
    with db.no_autoflush:
        return db.execute(statement).mappings().all()
