from datetime import date

from sqlalchemy.orm import Session


from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User


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
        db.query(Payment, Reservation, RoomType, User, Hotel)
        .join(Reservation, Payment.reservation_id == Reservation.reservation_id)
        .join(User, Reservation.user_id == User.user_id)
        .join(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .join(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .filter(Reservation.user_id == user_id)
        .all()
    )

    return [
        {
            "payment_id": payment.payment_id,
            "bill_to": user.full_name,
            "hotel_name": hotel.name,
            "room_type_name": room_type.type_name,
            "check_in_date": reservation.check_in_date,
            "check_out_date": reservation.check_out_date,
            "created_at": payment.created_at,
        }
        for payment, reservation, room_type, user, hotel, in res
    ]


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
        db.query(Payment, Reservation, RoomType, User, Hotel)
        .join(Reservation, Payment.reservation_id == Reservation.reservation_id)
        .join(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .join(User, Reservation.user_id == User.user_id)
        .join(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .filter(
            Payment.payment_id == payment_id,
            Reservation.user_id == user_id,
        )
        .first()
    )
    if res is None:
        return None

    (
        payment,
        reservation,
        room_type,
        user,
        hotel,
    ) = res

    return {
        "payment_id": payment.payment_id,
        "bill_to": user.full_name,
        "hotel_name": hotel.name,
        "room_type_name": room_type.type_name,
        "check_in_date": reservation.check_in_date,
        "check_out_date": reservation.check_out_date,
        "created_at": payment.created_at,
    }


def check_if_user_booked_by_date_range(
    db: Session, user_id: int, check_in_date: date, check_out_date: date
) -> bool:
    """
    Check if the user has any booking that overlaps
    with the given check-in and check-out date range.
    """

    return (
        db.query(Reservation)
        .filter(
            Reservation.user_id == user_id,
            Reservation.status != "cancelled",
            Reservation.check_in_date < check_out_date,
            Reservation.check_out_date > check_in_date,
        )
        .first()
        is not None
    )


def get_reservation_for_cancellation(db: Session, reservation_id: int, user_id: int):
    """Lock only the authenticated user's reservation for cancellation."""
    return (
        db.query(Reservation)
        .filter(Reservation.reservation_id == reservation_id)
        .filter(Reservation.user_id == user_id)
        .with_for_update()
        .first()
    )


def get_payments_for_cancellation(db: Session, reservation_id: int):
    """Lock all payments after the owned reservation has been locked."""
    return (
        db.query(Payment)
        .filter(Payment.reservation_id == reservation_id)
        .order_by(Payment.payment_id)
        .with_for_update()
        .all()
    )
