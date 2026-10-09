from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.hotel import Hotel
from app.schemas.booking_schema import (
    BookingResponse,
    BookingRequest,
    CancellationResponse,
    PaymentResponse,
)
from app.models.payment import Payment
from app.repositories import booking_dao
from app.config.constants import Constants
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.schemas.hotel_schema import HotelRevalidationRequest
from app.services import hotel_service

cancellation_fee = Constants.CANCELLATION_FEE
MONEY_CENT = Decimal("0.01")
MAX_MONEY = Decimal("99999999.99")  # DECIMAL(10, 2) in the initialization SQL


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_CENT, rounding=ROUND_HALF_UP)


def create_booking(db: Session, booking_info: BookingRequest, user_id: int) -> BookingResponse:
    """Recheck the accepted property quote before one atomic local booking write."""
    try:
        nights = (booking_info.check_out_date - booking_info.check_in_date).days
        if nights <= 0:
            raise HTTPException(status_code=422, detail="Check-out must be after check-in")

        quote = hotel_service.revalidate_hotel(
            HotelRevalidationRequest(
                property_token=booking_info.hotel_token,
                q=booking_info.q,
                check_in_date=booking_info.check_in_date,
                check_out_date=booking_info.check_out_date,
                adults=booking_info.adults,
                children=booking_info.children,
                currency=booking_info.currency,
                gl=booking_info.gl,
                hl=booking_info.hl,
            )
        )
        nightly_price = _money(Decimal(str(quote.current_price_per_night)))
        payment_amount = _money(Decimal(str(quote.likehome_payment_amount)))
        if (
            _money(Decimal(str(booking_info.price_per_night))) != nightly_price
            or _money(Decimal(str(booking_info.accepted_payment_amount))) != payment_amount
        ):
            raise HTTPException(status_code=409, detail="Rate changed; revalidate and review the current quote")
        total_price = Decimal(str(quote.likehome_reservation_total))
        if nightly_price > MAX_MONEY or total_price > MAX_MONEY or payment_amount > MAX_MONEY:
            raise HTTPException(status_code=422, detail="Booking amount exceeds supported range")

        # Authentication's earlier plain SELECT may have established an old
        # REPEATABLE READ snapshot. End that read-only transaction before the
        # booking critical section so the overlap read sees commits made while
        # waiting for this user's row lock. No booking writes have begun yet.
        db.rollback()
        if not booking_dao.lock_user_for_booking(db, user_id):
            raise HTTPException(
                status_code=401,
                detail="User is inactive or does not exist",
                headers={"WWW-Authenticate": "Bearer"},
            )

        booked = booking_dao.check_if_user_booked_by_date_range(
            db, user_id, booking_info.check_in_date, booking_info.check_out_date
        )
        if booked:
            raise HTTPException(
                status_code=400,
                detail="User already has a booking that overlaps with the given date.",
            )

        hotel = Hotel(
            name=quote.hotel_name,
            hotel_token=quote.property_token,
        )
        hotel_id = booking_dao.is_hotel_in_db(db, hotel)
        if hotel_id is None:
            hotel_id = booking_dao.stage_booking_record(db, hotel).hotel_id

        room_type = RoomType(
            hotel_id=hotel_id,
            type_name="Lowest available rate",
            description=f"Provider: {quote.source[:480]}",
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
                guest_full_name=booking_info.guest_full_name,
                guest_email=booking_info.guest_email,
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


def pay_booking_payment(db: Session, payment_id: int, user_id: int) -> PaymentResponse:
    """Mark one owned booking payment paid inside LikeHome; no external charge occurs."""
    try:
        reservation_id = booking_dao.get_owned_payment_reservation_id(db, payment_id, user_id)
        if reservation_id is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        # Authentication and ownership reads may have opened a REPEATABLE READ
        # snapshot. Lock the reservation first, matching cancellation order.
        db.rollback()
        reservation = booking_dao.lock_owned_reservation(db, reservation_id, user_id)
        if reservation is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        payment = booking_dao.lock_booking_payment(db, payment_id, reservation_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.payment_type != "booking" or reservation.status == "cancelled":
            raise HTTPException(status_code=409, detail="Payment cannot be completed")
        if payment.payment_status not in ("pending", "paid"):
            raise HTTPException(status_code=409, detail="Payment cannot be completed")
        if payment.payment_status == "pending":
            if reservation.status != "confirmed":
                raise HTTPException(status_code=409, detail="Payment cannot be completed")
            payment.payment_status = "paid"
            reservation.revision += 1
            result = PaymentResponse(**booking_dao.payment_result(payment))
            db.commit()
            return result
        return PaymentResponse(**booking_dao.payment_result(payment))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to record payment") from exc


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
        if booking_payment.payment_status not in ("pending", "paid"):
            raise HTTPException(status_code=409, detail="Reservation payment state is ambiguous")
        reservation.status = "cancelled"
        reservation.revision += 1
        if booking_payment.payment_status == "paid":
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
