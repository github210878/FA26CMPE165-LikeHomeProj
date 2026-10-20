"""Owner-scoped, projection-only reads for reservation-change reviews."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType


def get_owned_review_rows(db: Session, reservation_id: int, user_id: int):
    """Read the reservation and *all* its payments in one consistent statement.

    Outer joins retain missing property/payment associations for fail-closed
    validation. Never load guest details, take write locks, or flush caller state.
    A review does not hold inventory or promise that this snapshot stays current.
    """
    statement = (
        select(
            Reservation.reservation_id,
            Reservation.user_id,
            Reservation.room_type_id,
            Reservation.check_in_date,
            Reservation.check_out_date,
            Reservation.total_price,
            Reservation.status,
            RoomType.room_type_id.label("resolved_room_type_id"),
            RoomType.hotel_id,
            RoomType.price_per_night,
            Hotel.hotel_id.label("resolved_hotel_id"),
            Hotel.hotel_token,
            Payment.payment_id,
            Payment.amount,
            Payment.payment_type,
            Payment.payment_status,
        )
        .select_from(Reservation)
        .outerjoin(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .outerjoin(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .outerjoin(Payment, Reservation.reservation_id == Payment.reservation_id)
        .where(
            Reservation.reservation_id == reservation_id,
            Reservation.user_id == user_id,
        )
        .order_by(Payment.payment_id)
    )
    with db.no_autoflush:
        return db.execute(statement).mappings().all()
