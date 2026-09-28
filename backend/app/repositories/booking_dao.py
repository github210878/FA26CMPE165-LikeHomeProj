from datetime import date

from sqlalchemy.orm import Session


from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.models.user import User


def is_hotel_in_db(db: Session, target_hotel: Hotel):
    """
    Check if a hotel with the given address exists in the database.
    """
    hotel = (
        db.query(Hotel)
        .filter(
            Hotel.name == target_hotel.name,
            Hotel.street == target_hotel.street,
            Hotel.city == target_hotel.city,
            Hotel.state == target_hotel.state,
            Hotel.zip_code == target_hotel.zip_code,
            Hotel.country == target_hotel.country,
        )
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
            "hotel_address": hotel.street
            + ", "
            + hotel.city
            + ", "
            + hotel.state
            + ". "
            + hotel.zip_code
            + " "
            + hotel.country,
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


def get_booking_by_id(db: Session, booking_id: int):

    res = (
        db.query(Reservation, RoomType, Hotel)
        .join(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .join(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .filter(Reservation.reservation_id == booking_id)
        .first()
    )
    if res is None:
        return None

    reservation, room_type, hotel = res

    return {
        "reservation_id": reservation.reservation_id,
        "hotel_name": hotel.name,
        "room_type_name": room_type.type_name,
        "hotel_address": hotel.street
        + ", "
        + hotel.city
        + ", "
        + hotel.state
        + ". "
        + hotel.zip_code
        + " "
        + hotel.country,
        "hotel_phone": hotel.phone,
        "hotel_description": hotel.description,
        "room_description": room_type.description,
        "check_in_date": reservation.check_in_date,
        "check_out_date": reservation.check_out_date,
        "price_per_night": room_type.price_per_night,
        "total_price": reservation.total_price,
        "status": reservation.status,
    }


def get_payment_by_id(db: Session, payment_id: int):
    res = (
        db.query(Payment, Reservation, RoomType, User, Hotel)
        .join(Reservation, Payment.reservation_id == Reservation.reservation_id)
        .join(RoomType, Reservation.room_type_id == RoomType.room_type_id)
        .join(User, Reservation.user_id == User.user_id)
        .join(Hotel, RoomType.hotel_id == Hotel.hotel_id)
        .filter(Payment.payment_id == payment_id)
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
            Reservation.check_in_date < check_out_date,
            Reservation.check_out_date > check_in_date,
        )
        .first()
        is not None
    )


def cancel_booking(db: Session, reservation_id: int):
    """
    Cancel a booking by updating its status to 'cancelled'.
    """
    reservation = (
        db.query(Reservation)
        .filter(Reservation.reservation_id == reservation_id)
        .first()
    )
    reservation.status = "cancelled"
    db.commit()
    db.refresh(reservation)
    return reservation


def get_payment_by_booking_id(db: Session, reservation: int):
    """
    Retrieve the payment associated with a specific booking ID.
    """
    return (
        db.query(Payment)
        .join(Reservation, Payment.reservation_id == Reservation.reservation_id)
        .filter(Reservation.reservation_id == reservation)
        .first()
    )


def update_payment_status(db: Session, payment_id: int, new_status: str):
    payment = db.query(Payment).filter(Payment.payment_id == payment_id).first()
    if payment:
        payment.payment_status = new_status
        db.commit()
        db.refresh(payment)
        return payment
    else:
        return None
