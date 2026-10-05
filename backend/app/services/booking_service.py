from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.hotel import Hotel
from app.schemas.booking_schema import (
    BookingResponse,
    BookingRequest,
)
from app.models.payment import Payment
from app.repositories import booking_dao
from app.config.constants import Constants
from app.models.reservation import Reservation
from app.models.room_type import RoomType

# constants
sale_tax = Constants.SALE_TAX
service_fee = Constants.SERVICE_FEE
cancellation_fee = Constants.CANCELLATION_FEE


def create_booking(db: Session, booking_info: BookingRequest, user_id: int):

    booked = booking_dao.check_if_user_booked_by_date_range(
        db,
        user_id,
        booking_info.check_in_date,
        booking_info.check_out_date,
    )

    if booked:
        raise HTTPException(
            status_code=400,
            detail="User already has a booking that overlaps with the given date.",
        )

    hotel = Hotel(
        name=booking_info.hotel_name,
        token=booking_info.hotel_token,
        description=booking_info.hotel_description,
        street=booking_info.hotel_street,
        city=booking_info.hotel_city,
        state=booking_info.hotel_state,
        zip_code=booking_info.hotel_zip_code,
        country=booking_info.hotel_country,
        phone=booking_info.hotel_phone,
    )

    check_hotel = booking_dao.is_hotel_in_db(db, hotel)
    if check_hotel is None:
        hotel = booking_dao.create_hotel(db, hotel)
    else:
        hotel.hotel_id = check_hotel

    room_type = RoomType(
        hotel_id=hotel.hotel_id,
        type_name=booking_info.room_type_name,
        description=booking_info.room_type_description,
        price_per_night=booking_info.price_per_night,
    )

    check_room_type = booking_dao.is_room_type_in_db(db, room_type)
    if check_room_type is None:
        room_type = booking_dao.create_room_type(db, room_type)
    else:
        room_type.room_type_id = check_room_type

    reservation = Reservation(
        user_id=user_id,
        room_type_id=room_type.room_type_id,
        check_in_date=booking_info.check_in_date,
        check_out_date=booking_info.check_out_date,
        total_price=room_type.price_per_night * service_fee,
        status="confirmed",
    )

    reservation = booking_dao.create_reservation(db, reservation)

    payment = Payment(
        reservation_id=reservation.reservation_id,
        amount=reservation.total_price * sale_tax,
        payment_type="booking",
        payment_status="Pending",
    )

    payment = booking_dao.create_payment(db, payment)

    return BookingResponse(
        user_id=user_id,
        hotel_id=hotel.hotel_id,
        room_type_id=room_type.room_type_id,
        reservation_id=reservation.reservation_id,
        payment_id=payment.payment_id,
    )


def get_all_booking_by_user_id(db: Session, user_id: int):
    return booking_dao.get_all_booking_by_user_id(db, user_id)


def get_all_payments_by_user_id(db: Session, user_id: int):
    return booking_dao.get_all_payments_by_user_id(db, user_id)


def get_booking_by_id(db: Session, booking_id: int, user_id: int):
    return booking_dao.get_booking_by_id(db, booking_id, user_id)


def get_payment_by_id(db: Session, payment_id: int, user_id: int):
    return booking_dao.get_payment_by_id(db, payment_id, user_id)


def cancel_booking(db: Session, booking_id: int, user_id: int):
    reservation = booking_dao.get_booking_by_id(db, booking_id, user_id)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    updated_reservation = booking_dao.cancel_booking(db, booking_id, user_id)
    if not updated_reservation:
        raise HTTPException(status_code=404, detail="Fail to cancel reservation")

    payment = booking_dao.get_payment_by_booking_id(db, booking_id, user_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    updated_payment = booking_dao.update_payment_status(
        db, payment.payment_id, "refunded"
    )
    if not updated_payment:
        raise HTTPException(status_code=404, detail="Fail to update payment")

    cancellation_payment = Payment(
        reservation_id=reservation["reservation_id"],
        amount=reservation["total_price"] * cancellation_fee,
        payment_type="cancellation",
        payment_status="Pending",
    )

    payment = booking_dao.create_payment(db, cancellation_payment)

    return {
        "reservation": reservation,
        "cancellation_payment": cancellation_payment,
    }
