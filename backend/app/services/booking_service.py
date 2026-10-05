from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.hotel import Hotel
from app.schemas.booking_schema import (
    BookingResponse,
    BookingRequest,
    CancellationResponse,
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
MONEY_CENT = Decimal("0.01")
MAX_MONEY = Decimal("99999999.99")  # DECIMAL(10, 2) in the initialization SQL


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_CENT, rounding=ROUND_HALF_UP)


def create_booking(db: Session, booking_info: BookingRequest, user_id: int) -> BookingResponse:
    """Persist a booking in one transaction; the submitted rate is not verified."""
    try:
        nights = (booking_info.check_out_date - booking_info.check_in_date).days
        if nights <= 0:
            raise HTTPException(status_code=422, detail="Check-out must be after check-in")

        nightly_price = _money(Decimal(str(booking_info.price_per_night)))
        if nightly_price <= 0:
            raise HTTPException(status_code=422, detail="Nightly price rounds to zero")
        total_price = _money(nightly_price * nights * Decimal(str(service_fee)))
        payment_amount = _money(total_price * Decimal(str(sale_tax)))
        if nightly_price > MAX_MONEY or total_price > MAX_MONEY or payment_amount > MAX_MONEY:
            raise HTTPException(status_code=422, detail="Booking amount exceeds supported range")

        booked = booking_dao.check_if_user_booked_by_date_range(
            db, user_id, booking_info.check_in_date, booking_info.check_out_date
        )
        if booked:
            raise HTTPException(
                status_code=400,
                detail="User already has a booking that overlaps with the given date.",
            )

        hotel = Hotel(
            name=booking_info.hotel_name,
            hotel_token=booking_info.hotel_token,
            description=booking_info.hotel_description,
            street=booking_info.hotel_street,
            city=booking_info.hotel_city,
            state=booking_info.hotel_state,
            zip_code=booking_info.hotel_zip_code,
            country=booking_info.hotel_country,
            phone=booking_info.hotel_phone,
        )
        hotel_id = booking_dao.is_hotel_in_db(db, hotel)
        if hotel_id is None:
            hotel_id = booking_dao.stage_booking_record(db, hotel).hotel_id

        room_type = RoomType(
            hotel_id=hotel_id,
            type_name=booking_info.room_type_name,
            description=booking_info.room_type_description,
            price_per_night=float(nightly_price),
        )
        room_type_id = booking_dao.is_room_type_in_db(db, room_type)
        if room_type_id is None:
            room_type_id = booking_dao.stage_booking_record(db, room_type).room_type_id

        reservation = booking_dao.stage_booking_record(
            db,
            Reservation(
                user_id=user_id,
                room_type_id=room_type_id,
                check_in_date=booking_info.check_in_date,
                check_out_date=booking_info.check_out_date,
                total_price=float(total_price),
                status="confirmed",
            ),
        )
        payment = booking_dao.stage_booking_record(
            db,
            Payment(
                reservation_id=reservation.reservation_id,
                amount=float(payment_amount),
                payment_type="booking",
                payment_status="pending",
            ),
        )
        response = BookingResponse(
            user_id=user_id,
            hotel_id=hotel_id,
            room_type_id=room_type_id,
            reservation_id=reservation.reservation_id,
            payment_id=payment.payment_id,
        )
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create reservation") from exc


def get_all_booking_by_user_id(db: Session, user_id: int):
    return booking_dao.get_all_booking_by_user_id(db, user_id)


def get_all_payments_by_user_id(db: Session, user_id: int):
    return booking_dao.get_all_payments_by_user_id(db, user_id)


def get_booking_by_id(db: Session, booking_id: int, user_id: int):
    return booking_dao.get_booking_by_id(db, booking_id, user_id)


def get_payment_by_id(db: Session, payment_id: int, user_id: int):
    return booking_dao.get_payment_by_id(db, payment_id, user_id)


def cancel_booking(db: Session, booking_id: int, user_id: int) -> CancellationResponse:
    """Record a cancellation atomically; this does not process an external refund."""
    try:
        reservation = booking_dao.get_reservation_for_cancellation(
            db, booking_id, user_id
        )
        if reservation is None:
            raise HTTPException(status_code=404, detail="Reservation not found")
        if reservation.status != "confirmed":
            raise HTTPException(
                status_code=409, detail="Reservation cannot be cancelled"
            )

        payments = booking_dao.get_payments_for_cancellation(
            db, reservation.reservation_id
        )
        booking_payments = [p for p in payments if p.payment_type == "booking"]
        if len(booking_payments) != 1 or any(
            p.payment_type == "cancellation" for p in payments
        ):
            raise HTTPException(
                status_code=409, detail="Reservation payment state is ambiguous"
            )

        booking_payment = booking_payments[0]
        reservation.status = "cancelled"
        booking_payment.payment_status = "refunded"
        cancellation_payment = Payment(
            reservation_id=reservation.reservation_id,
            amount=reservation.total_price * cancellation_fee,
            payment_type="cancellation",
            payment_status="pending",
        )
        db.add(cancellation_payment)
        db.flush()
        response = CancellationResponse(
            reservation_id=reservation.reservation_id,
            status=reservation.status,
            booking_payment_id=booking_payment.payment_id,
            booking_payment_status=booking_payment.payment_status,
            cancellation_payment_id=cancellation_payment.payment_id,
            cancellation_amount=cancellation_payment.amount,
            cancellation_payment_status=cancellation_payment.payment_status,
        )
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to cancel reservation") from exc
