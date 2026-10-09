from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy import select


from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.reservation_change_event import ReservationChangeEvent
from app.models.reservation_change_adjustment import ReservationChangeAdjustment
from app.models.room_type import RoomType
from app.models.user import User


def lock_user_for_booking(db: Session, user_id: int) -> bool:
    """Serialize this user's booking writes on a stable row, even with no stays."""
    statement = (
        select(User.user_id)
        .where(User.user_id == user_id, User.status == "active")
        .with_for_update()
    )
    return db.execute(statement).scalar_one_or_none() is not None


def format_hotel_address(hotel: Hotel) -> str:
    """Keep the booking address readable when hotel address columns are null."""
    location = ", ".join(
        part.strip()
        for part in (hotel.street, hotel.city, hotel.state)
        if part and part.strip()
    )
    postal = " ".join(
        part.strip()
        for part in (hotel.zip_code, hotel.country)
        if part and part.strip()
    )
    return ". ".join(part for part in (location, postal) if part)


def is_hotel_in_db(db: Session, target_hotel: Hotel):
    """
    A hotel token, not a mutable name or address, identifies a persisted hotel.
    """
    if not target_hotel.hotel_token:
        raise ValueError("hotel_token is required to look up a hotel")
    hotel = (
        db.query(Hotel)
        .filter(Hotel.hotel_token == target_hotel.hotel_token)
        .first()
    )
    if hotel is not None:
        return hotel.hotel_id
    return None


def is_room_type_in_db(db: Session, target_room_type: RoomType):
    """
    Check if a room type with the given hotel exists in the database.
    """
    room_type = (
        db.query(RoomType)
        .filter(
            RoomType.hotel_id == target_room_type.hotel_id,
            RoomType.type_name == target_room_type.type_name,
            RoomType.description == target_room_type.description,
            RoomType.price_per_night == target_room_type.price_per_night,
        )
        .first()
    )
    if room_type is not None:
        return room_type.room_type_id
    return None


def get_hotel_by_id(db: Session, hotel_id: int):
    """
    Retrieve a hotel by its ID.
    """
    return db.query(Hotel).filter(Hotel.hotel_id == hotel_id).first()


def create_hotel(db: Session, hotel: Hotel):
    """
    Create a new hotel in the database.
    """
    db.add(hotel)
    db.commit()
    db.refresh(hotel)
    return hotel


def create_room_type(db: Session, room_type):
    """
    Create a new room type in the database.
    """
    db.add(room_type)
    db.commit()
    db.refresh(room_type)
    return room_type


def create_reservation(db: Session, reservation):
    """
    Create a new reservation in the database.
    """
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation


def create_payment(db: Session, payment):
    """
    Create a new payment in the database.
    """
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def stage_booking_record(db: Session, record):
    """Assign generated IDs during booking creation without committing."""
    db.add(record)
    db.flush()
    return record


def get_all_booking_by_user_id(db: Session, user_id: int):

    res = (
        db.query(Reservation, RoomType, Hotel)
        .join(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .join(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .filter(Reservation.user_id == user_id)
        .all()
    )

    return [
        {
            "reservation_id": reservation.reservation_id,
            "hotel_name": hotel.name,
            "room_type_name": room_type.type_name,
            "hotel_address": format_hotel_address(hotel),
            "hotel_phone": hotel.phone,
            "hotel_description": hotel.description,
            "room_description": room_type.description,
            "check_in_date": reservation.check_in_date,
            "check_out_date": reservation.check_out_date,
            "price_per_night": room_type.price_per_night,
            "total_price": reservation.total_price,
            "status": reservation.status,
        }
        for reservation, room_type, hotel in res
    ]


def get_all_payments_by_user_id(db: Session, user_id: int):
    res = (
        db.query(Payment)
        .join(Reservation, Payment.reservation_id == Reservation.reservation_id)
        .filter(Reservation.user_id == user_id)
        .all()
    )
    return [payment_result(payment) for payment in res]


def get_booking_by_id(db: Session, booking_id: int, user_id: int):

    res = (
        db.query(Reservation, RoomType, Hotel)
        .join(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .join(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .filter(
            Reservation.reservation_id == booking_id,
            Reservation.user_id == user_id,
        )
        .first()
    )
    if res is None:
        return None

    reservation, room_type, hotel = res

    return {
        "reservation_id": reservation.reservation_id,
        "guest_full_name": reservation.guest_full_name,
        "guest_email": reservation.guest_email,
        "hotel_name": hotel.name,
        "room_type_name": room_type.type_name,
        "hotel_address": format_hotel_address(hotel),
        "hotel_phone": hotel.phone,
        "hotel_description": hotel.description,
        "room_description": room_type.description,
        "check_in_date": reservation.check_in_date,
        "check_out_date": reservation.check_out_date,
        "price_per_night": room_type.price_per_night,
        "total_price": reservation.total_price,
        "status": reservation.status,
    }


def get_payment_by_id(db: Session, payment_id: int, user_id: int):
    res = (
        db.query(Payment)
        .join(Reservation, Payment.reservation_id == Reservation.reservation_id)
        .filter(
            Payment.payment_id == payment_id,
            Reservation.user_id == user_id,
        )
        .first()
    )
    if res is None:
        return None

    return payment_result(res)


def payment_result(payment: Payment):
    return {
        "payment_id": payment.payment_id,
        "reservation_id": payment.reservation_id,
        "amount": payment.amount,
        "payment_type": payment.payment_type,
        "payment_status": payment.payment_status,
    }


def get_owned_payment_reservation_id(db: Session, payment_id: int, user_id: int):
    return (
        db.query(Payment.reservation_id)
        .join(Reservation, Payment.reservation_id == Reservation.reservation_id)
        .filter(Payment.payment_id == payment_id, Reservation.user_id == user_id)
        .scalar()
    )


def lock_owned_reservation(db: Session, reservation_id: int, user_id: int):
    return (
        db.query(Reservation)
        .filter(Reservation.reservation_id == reservation_id, Reservation.user_id == user_id)
        .with_for_update()
        .first()
    )


def lock_booking_payment(db: Session, payment_id: int, reservation_id: int):
    return (
        db.query(Payment)
        .filter(Payment.payment_id == payment_id, Payment.reservation_id == reservation_id)
        .with_for_update()
        .first()
    )


def check_if_user_booked_by_date_range(
    db: Session, user_id: int, check_in_date: date, check_out_date: date,
    *, exclude_reservation_id: int | None = None,
) -> bool:
    """
    Check if the user has any booking that overlaps
    with the given check-in and check-out date range.
    """

    query = (
        db.query(Reservation)
        .filter(
            Reservation.user_id == user_id,
            Reservation.status != "cancelled",
            Reservation.check_in_date < check_out_date,
            Reservation.check_out_date > check_in_date,
        )
    )
    if exclude_reservation_id is not None:
        query = query.filter(Reservation.reservation_id != exclude_reservation_id)
    return query.first() is not None


def get_owned_reservation_for_change(db: Session, reservation_id: int, user_id: int):
    """Read an owned stay and its associations without acquiring mutation locks."""
    records = (
        db.query(Reservation, RoomType, Hotel)
        .outerjoin(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .outerjoin(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .filter(Reservation.reservation_id == reservation_id, Reservation.user_id == user_id)
        .populate_existing()
        .first()
    )
    if records is None:
        return None
    payments = (
        db.query(Payment)
        .filter(Payment.reservation_id == reservation_id)
        .order_by(Payment.payment_id)
        .populate_existing()
        .all()
    )
    reservation, room_type, hotel = records
    return reservation, room_type, hotel, payments


def is_active_booking_user(db: Session, user_id: int) -> bool:
    return db.execute(
        select(User.user_id).where(User.user_id == user_id, User.status == "active")
    ).scalar_one_or_none() is not None


def lock_reservation_for_change(db: Session, reservation_id: int, user_id: int):
    """Refresh the authoritative stay after the caller locks its User row."""
    return (
        db.query(Reservation)
        .filter(Reservation.reservation_id == reservation_id, Reservation.user_id == user_id)
        .populate_existing()
        .with_for_update()
        .first()
    )


def lock_payments_for_change(db: Session, reservation_id: int):
    return (
        db.query(Payment)
        .filter(Payment.reservation_id == reservation_id)
        .order_by(Payment.payment_id)
        .populate_existing()
        .with_for_update()
        .all()
    )


def get_adjustments_for_change(db: Session, reservation_id: int, *, lock: bool = False):
    change_ids = select(ReservationChangeEvent.change_id).where(
        ReservationChangeEvent.reservation_id == reservation_id,
    )
    query = (
        db.query(ReservationChangeAdjustment)
        .filter(ReservationChangeAdjustment.change_id.in_(change_ids))
        .order_by(ReservationChangeAdjustment.adjustment_id)
        .populate_existing()
    )
    return (query.with_for_update() if lock else query).all()


def get_latest_reservation_change(db: Session, reservation_id: int):
    return (
        db.query(ReservationChangeEvent)
        .filter(ReservationChangeEvent.reservation_id == reservation_id)
        .order_by(ReservationChangeEvent.revision_after.desc())
        .populate_existing()
        .first()
    )


def get_owned_change_adjustment(db: Session, adjustment_id: int, user_id: int):
    """Follow persisted adjustment/event/reservation/user ownership, without locks."""
    with db.no_autoflush:
        return (
            db.query(ReservationChangeAdjustment, ReservationChangeEvent, Reservation)
            .join(ReservationChangeEvent, ReservationChangeAdjustment.change_id == ReservationChangeEvent.change_id)
            .join(Reservation, ReservationChangeEvent.reservation_id == Reservation.reservation_id)
            .join(User, Reservation.user_id == User.user_id)
            .filter(
                ReservationChangeAdjustment.adjustment_id == adjustment_id,
                Reservation.user_id == user_id, ReservationChangeEvent.user_id == user_id,
                User.status == "active",
            )
            .populate_existing()
            .first()
        )


def get_reservation_change_history(db: Session, reservation_id: int):
    return (
        db.query(ReservationChangeEvent)
        .filter(ReservationChangeEvent.reservation_id == reservation_id)
        .order_by(ReservationChangeEvent.revision_after)
        .populate_existing()
        .all()
    )


def get_reservation_for_cancellation(db: Session, reservation_id: int, user_id: int):
    """Lock only the authenticated user's reservation for cancellation."""
    return (
        db.query(Reservation)
        .filter(Reservation.reservation_id == reservation_id)
        .filter(Reservation.user_id == user_id)
        .populate_existing()
        .with_for_update()
        .first()
    )


def get_owned_change_event_by_quote_jti(db: Session, quote_jti: str, reservation_id: int, user_id: int):
    """Read a receipt without writes/locks; final confirmation must recheck under locks."""
    with db.no_autoflush:
        return (
            db.query(ReservationChangeEvent)
            .join(Reservation, ReservationChangeEvent.reservation_id == Reservation.reservation_id)
            .filter(
                ReservationChangeEvent.quote_jti == quote_jti,
                ReservationChangeEvent.reservation_id == reservation_id,
                ReservationChangeEvent.user_id == user_id,
                Reservation.user_id == user_id,
            )
            .populate_existing()
            .first()
        )


def get_payments_for_cancellation(db: Session, reservation_id: int):
    """Lock all payments after the owned reservation has been locked."""
    return (
        db.query(Payment)
        .filter(Payment.reservation_id == reservation_id)
        .order_by(Payment.payment_id)
        .populate_existing()
        .with_for_update()
        .all()
    )
