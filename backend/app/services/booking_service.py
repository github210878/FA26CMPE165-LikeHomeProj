from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config.constants import Constants
from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.repositories import booking_dao, user_dao
from app.schemas.booking_schema import (
    BookingRequest,
    BookingResponse,
    CancellationChargeResponse,
    CancellationResponse,
    PaymentResponse,
)
from app.schemas.hotel_schema import HotelRevalidationRequest
from app.schemas.reservation_change_schema import (
    ReservationChangeQuoteRequest,
    ReservationDateChangeResponse,
)
from app.services import hotel_service, reservation_change_quote_service
from app.services.cancellation_policy import calculate_cancellation_fee
from app.services.payment_service import payment_service

cancellation_fee = Constants.CANCELLATION_FEE
reward_points_per_dollor = Constants.REWARD_POINTS_PER_DOLLAR
MONEY_CENT = Decimal("0.01")
MAX_MONEY = Decimal("99999999.99")  # DECIMAL(10, 2) in the initialization SQL
BOOKING_REFERENCE_PREFIX = "LH-"


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_CENT, rounding=ROUND_HALF_UP)


def _booking_reference(reservation_id: int) -> str:
    """Build a stable public reference from the committed reservation identity."""
    return f"{BOOKING_REFERENCE_PREFIX}{reservation_id:08d}"


def create_booking(
    db: Session, booking_info: BookingRequest, user_id: int
) -> BookingResponse:
    """Recheck the accepted property quote before one atomic local booking write."""
    try:
        nights = (booking_info.check_out_date - booking_info.check_in_date).days
        if nights <= 0:
            raise HTTPException(
                status_code=422, detail="Check-out must be after check-in"
            )

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
            or _money(Decimal(str(booking_info.accepted_payment_amount)))
            != payment_amount
        ):
            raise HTTPException(
                status_code=409,
                detail="Rate changed; revalidate and review the current quote",
            )
        total_price = Decimal(str(quote.likehome_reservation_total))
        if (
            nightly_price > MAX_MONEY
            or total_price > MAX_MONEY
            or payment_amount > MAX_MONEY
        ):
            raise HTTPException(
                status_code=422, detail="Booking amount exceeds supported range"
            )

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

        # Older API clients may omit occupancy. Preserve the existing checkout
        # defaults for them, but do not infer party size for later changes.
        booking_context = None
        if {"adults", "children"} <= booking_info.model_fields_set:
            booking_context = {
                "property_token": quote.property_token,
                "q": booking_info.q,
                "adults": booking_info.adults,
                "children": booking_info.children,
                "currency": booking_info.currency,
                "gl": booking_info.gl,
                "hl": booking_info.hl,
                "pending_amount": str(payment_amount),
                "nightly_price": float(nightly_price),
            }

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
                booking_context=booking_context,
            ),
        )
        payment = payment_service.create_pending_payment(
            db, reservation.reservation_id, float(payment_amount)
        )
        response = BookingResponse(
            user_id=user_id,
            hotel_id=hotel_id,
            room_type_id=room_type_id,
            reservation_id=reservation.reservation_id,
            payment_id=payment.payment_id,
            booking_reference=_booking_reference(reservation.reservation_id),
            status=reservation.status,
        )
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Failed to create reservation"
        ) from exc


def get_all_booking_by_user_id(db: Session, user_id: int):
    return booking_dao.get_all_booking_by_user_id(db, user_id)


def get_all_payments_by_user_id(db: Session, user_id: int):
    return booking_dao.get_all_payments_by_user_id(db, user_id)


def get_booking_by_id(db: Session, booking_id: int, user_id: int):
    return booking_dao.get_booking_by_id(db, booking_id, user_id)


def get_payment_by_id(db: Session, payment_id: int, user_id: int):
    return booking_dao.get_payment_by_id(db, payment_id, user_id)


def get_cancellation_charge(
    db: Session, reservation_id: int, user_id: int
) -> CancellationChargeResponse:
    """Preview an owned reservation's cancellation charge without side effects."""
    reservation = booking_dao.get_owned_reservation(db, reservation_id, user_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status != "confirmed":
        raise HTTPException(status_code=409, detail="Reservation cannot be cancelled")

    fee = calculate_cancellation_fee(reservation.total_price)
    return CancellationChargeResponse(
        reservation_id=reservation.reservation_id,
        reservation_total=float(_money(Decimal(str(reservation.total_price)))),
        cancellation_fee_rate=float(Constants.CANCELLATION_FEE),
        cancellation_charge=float(fee),
        reservation_status=reservation.status,
    )


def pay_booking_payment(db: Session, payment_id: int, user_id: int) -> PaymentResponse:
    """Commit one internal payment and its reward award together; no external charge."""
    try:
        reservation_id = booking_dao.get_owned_payment_reservation_id(
            db, payment_id, user_id
        )
        if reservation_id is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        # Authentication and ownership reads may have opened a REPEATABLE READ
        # snapshot. Start fresh, then lock User -> Reservation -> ordered Payments.
        # Booking creation also locks User first; cancellation locks only the
        # Reservation -> Payments suffix and never updates rewards.
        db.rollback()
        user = booking_dao.lock_active_user_for_payment(db, user_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="User is inactive or does not exist",
                headers={"WWW-Authenticate": "Bearer"},
            )
        reservation = booking_dao.lock_owned_reservation(db, reservation_id, user_id)
        if reservation is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        payment = booking_dao.lock_booking_payment(db, payment_id, reservation_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        transitioned = payment_service.complete_booking_payment(
            db, user, reservation, payment
        )
        if transitioned:
            result = PaymentResponse(**booking_dao.payment_result(payment))
            db.commit()
            return result
        # Paid is the award marker for new atomic transitions. Never infer a
        # missing historical award from the aggregate balance or retry it here.
        result = PaymentResponse(**booking_dao.payment_result(payment))
        db.rollback()
        return result
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
            raise HTTPException(
                status_code=409, detail="Reservation payment state is ambiguous"
            )
        reservation.status = "cancelled"
        if booking_payment.payment_status == "paid":
            booking_payment.payment_status = "refunded"
        cancellation_payment = payment_service.create_cancellation_payment(
            db,
            reservation.reservation_id,
            float(calculate_cancellation_fee(reservation.total_price)),
        )
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
        raise HTTPException(
            status_code=500, detail="Failed to cancel reservation"
        ) from exc


def pay_cancellation_fee(db: Session, payment_id: int, user_id: int) -> PaymentResponse:
    """Mark one owned cancellation fee paid inside LikeHome; no external charge occurs."""
    try:
        reservation_id = booking_dao.get_owned_payment_reservation_id(
            db, payment_id, user_id
        )
        if reservation_id is None:
            raise HTTPException(status_code=404, detail="Payment not found")

        db.rollback()
        reservation = booking_dao.lock_owned_reservation(db, reservation_id, user_id)
        if reservation is None:
            raise HTTPException(status_code=404, detail="Payment not found")

        payment = booking_dao.lock_booking_payment(db, payment_id, reservation_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment not found")

        if payment.payment_type != "cancellation" or reservation.status != "cancelled":
            raise HTTPException(status_code=409, detail="Payment cannot be completed")

        if payment.payment_status not in ("pending", "paid"):
            raise HTTPException(status_code=409, detail="Payment cannot be completed")

        if payment.payment_status == "pending":
            payment.payment_status = "paid"
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


def pay_with_reward_points(
    db: Session, payment_id: int, user_id: int
) -> PaymentResponse:
    """Pay an owned booking in full with reward points atomically."""
    try:
        reservation_id = booking_dao.get_owned_payment_reservation_id(
            db, payment_id, user_id
        )
        if reservation_id is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        # Refresh the snapshot, then serialize user -> reservation -> payment.
        db.rollback()
        user = booking_dao.lock_active_user_for_payment(db, user_id)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="User is inactive or does not exist",
                headers={"WWW-Authenticate": "Bearer"},
            )
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
                raise HTTPException(
                    status_code=409, detail="Payment cannot be completed"
                )
            try:
                amount = Decimal(str(payment.amount))
            except (InvalidOperation, ValueError):
                raise HTTPException(
                    status_code=409, detail="Payment amount is unsupported"
                ) from None
            if (
                not amount.is_finite()
                or amount <= 0
                or amount > MAX_MONEY
                or amount != _money(amount)
            ):
                raise HTTPException(
                    status_code=409, detail="Payment amount is unsupported"
                )
            required_points = int(amount * Decimal(str(reward_points_per_dollor)))
            if type(user.reward_points) is not int or user.reward_points < required_points:
                raise HTTPException(status_code=409, detail="Not enough reward points")
            user.reward_points -= required_points
            db.flush()
            user_dao.create_redeem_history(
                db=db,
                user_id=user_id,
                reward_points_redeemed=required_points,
                redemption_type="free_stay",
                payment_id=payment.payment_id,
                reservation_id=reservation.reservation_id,
                commit=False,
            )
            payment.payment_status = "paid"
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


def _date_change_records(
    db: Session, reservation_id: int, user_id: int, *, lock: bool = False,
) -> tuple[Reservation, Payment]:
    get_reservation = booking_dao.lock_owned_reservation if lock else booking_dao.get_owned_reservation
    reservation = get_reservation(db, reservation_id, user_id)
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status != "confirmed":
        raise HTTPException(status_code=409, detail={"code": "reservation_not_confirmed"})

    payments = booking_dao.get_reservation_payments(db, reservation_id, lock=lock)
    if len(payments) != 1 or payments[0].payment_type != "booking":
        raise HTTPException(status_code=409, detail={"code": "payment_unsupported"})
    payment = payments[0]
    if payment.payment_status != "pending":
        raise HTTPException(status_code=409, detail={"code": "payment_unsupported"})
    return reservation, payment


def _date_change_snapshot(db: Session, reservation: Reservation, payment: Payment) -> tuple:
    room = db.get(RoomType, reservation.room_type_id)
    hotel = db.get(Hotel, room.hotel_id) if room else None
    return (
        reservation.room_type_id, hotel.hotel_token if hotel else None,
        reservation.check_in_date, reservation.check_out_date, reservation.total_price,
        reservation.booking_context, payment.payment_id, payment.amount,
    )


def _date_change_result(
    reservation: Reservation, payment: Payment, *, changed: bool,
) -> ReservationDateChangeResponse:
    return ReservationDateChangeResponse(
        reservation_id=reservation.reservation_id,
        payment_id=payment.payment_id,
        booking_reference=_booking_reference(reservation.reservation_id),
        check_in_date=reservation.check_in_date,
        check_out_date=reservation.check_out_date,
        total_price=reservation.total_price,
        payment_amount=payment.amount,
        changed=changed,
    )


def change_booking_dates(
    db: Session, reservation_id: int, dates: ReservationChangeQuoteRequest, user_id: int,
) -> ReservationDateChangeResponse:
    """Save a same-property date change within the existing pending payment approval."""
    requested_dates = dates.check_in_date, dates.check_out_date
    try:
        reservation, payment = _date_change_records(db, reservation_id, user_id)
        quote = None
        snapshot = None
        if requested_dates != (reservation.check_in_date, reservation.check_out_date):
            snapshot = _date_change_snapshot(db, reservation, payment)
            context = reservation.booking_context
            provider_keys = {"property_token", "q", "adults", "children", "currency", "gl", "hl"}
            required = provider_keys | {"pending_amount", "nightly_price"}
            if (
                not isinstance(context, dict) or set(context) != required
                or not snapshot[1] or snapshot[1] != context["property_token"]
                or type(context["adults"]) is not int or type(context["children"]) is not int
            ):
                raise HTTPException(status_code=409, detail={"code": "booking_context_missing"})
            provider_fields = {key: context[key] for key in provider_keys}
            try:
                info = HotelRevalidationRequest(**provider_fields, **dates.model_dump())
                accepted_amount = Decimal(context["pending_amount"])
                if not accepted_amount.is_finite() or not 0 < accepted_amount <= MAX_MONEY:
                    raise ValueError("Invalid accepted amount")
            except (ValidationError, ArithmeticError, TypeError, ValueError):
                raise HTTPException(status_code=409, detail={"code": "booking_context_missing"}) from None
            if accepted_amount != Decimal(str(payment.amount)):
                raise HTTPException(status_code=409, detail={"code": "payment_unsupported"})

            # Release the read transaction before asking the hotel provider.
            db.rollback()
            try:
                quote = reservation_change_quote_service.validate_revalidated_quote(
                    hotel_service.revalidate_hotel(info), info,
                )
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=502, detail="Hotel availability could not be verified") from None
            if Decimal(str(quote.likehome_payment_amount)) > accepted_amount:
                raise HTTPException(status_code=409, detail={"code": "price_increase"})

        # Start a fresh snapshot and serialize with create_booking before reading overlaps.
        db.rollback()
        if not booking_dao.lock_user_for_booking(db, user_id):
            raise HTTPException(status_code=401, detail="User is inactive or does not exist",
                                headers={"WWW-Authenticate": "Bearer"})
        reservation, payment = _date_change_records(db, reservation_id, user_id, lock=True)
        if requested_dates == (reservation.check_in_date, reservation.check_out_date):
            result = _date_change_result(reservation, payment, changed=False)
            db.rollback()
            return result
        if quote is None or snapshot != _date_change_snapshot(db, reservation, payment):
            raise HTTPException(status_code=409, detail={"code": "reservation_changed"})
        if booking_dao.check_if_user_booked_by_date_range(
            db, user_id, *requested_dates, excluded_reservation_id=reservation_id,
        ):
            raise HTTPException(status_code=409, detail={"code": "dates_overlap"})

        reservation.check_in_date, reservation.check_out_date = requested_dates
        reservation.total_price = quote.likehome_reservation_total
        payment.amount = quote.likehome_payment_amount
        reservation.booking_context = {
            **reservation.booking_context,
            "pending_amount": str(_money(Decimal(str(payment.amount)))),
            "nightly_price": quote.current_price_per_night,
        }
        result = _date_change_result(reservation, payment, changed=True)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to change reservation dates") from exc


def modify_booking(
    db: Session,
    reservation_id: int,
    booking_info: BookingRequest,
    user_id: int,
) -> BookingResponse:
    """Modify an existing confirmed booking transactionally."""
    try:
        # Verify ownership and reservation existence.
        reservation = booking_dao.get_reservation_by_id(
            db,
            reservation_id,
            user_id,
        )

        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail="Reservation not found",
            )

        if reservation.status != "confirmed":
            raise HTTPException(
                status_code=409,
                detail="Reservation cannot be modified",
            )

        nights = (booking_info.check_out_date - booking_info.check_in_date).days

        if nights <= 0:
            raise HTTPException(
                status_code=422,
                detail="Check-out must be after check-in",
            )

        # Revalidate the latest hotel quote.
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
        total_price = _money(Decimal(str(quote.likehome_reservation_total)))

        # Verify that the client quote is still current.
        if (
            _money(Decimal(str(booking_info.price_per_night))) != nightly_price
            or _money(Decimal(str(booking_info.accepted_payment_amount)))
            != payment_amount
        ):
            raise HTTPException(
                status_code=409,
                detail=("Rate changed; " "revalidate and review the current quote"),
            )

        if (
            nightly_price > MAX_MONEY
            or total_price > MAX_MONEY
            or payment_amount > MAX_MONEY
        ):
            raise HTTPException(
                status_code=422,
                detail="Booking amount exceeds supported range",
            )

        # End the previous read transaction before locking rows.
        db.rollback()

        # Lock the reservation and reload the latest state.
        reservation = booking_dao.lock_owned_reservation(
            db,
            reservation_id,
            user_id,
        )

        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail="Reservation not found",
            )

        if reservation.status != "confirmed":
            raise HTTPException(
                status_code=409,
                detail="Reservation cannot be modified",
            )

        # This endpoint only modifies the existing hotel booking.
        existing_hotel = db.get(
            Hotel,
            reservation.room_type.hotel_id,
        )

        if existing_hotel is None or existing_hotel.hotel_token != quote.property_token:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Changing the hotel is not supported "
                    "when modifying a reservation"
                ),
            )

        # Check whether the new dates overlap with another booking.
        # The current reservation must be excluded from this check.
        has_overlap = booking_dao.check_if_user_booked_by_date_range_excluding(
            db,
            user_id,
            booking_info.check_in_date,
            booking_info.check_out_date,
            reservation_id,
        )

        if has_overlap:
            raise HTTPException(
                status_code=409,
                detail=(
                    "User already has another booking "
                    "that overlaps with the given date"
                ),
            )

        # Find and lock the related booking payment.
        payment_id = booking_dao.get_payment_id_by_reservation_id(
            db,
            reservation_id,
        )

        if payment_id is None:
            raise HTTPException(
                status_code=409,
                detail="Booking payment not found",
            )

        payment = booking_dao.lock_booking_payment(
            db,
            payment_id,
            reservation_id,
        )

        if payment is None:
            raise HTTPException(
                status_code=409,
                detail="Booking payment not found",
            )

        if payment.payment_type != "booking":
            raise HTTPException(
                status_code=409,
                detail="Invalid booking payment",
            )

        # A paid reservation cannot be modified.
        # The user must request a refund first.
        if payment.payment_status == "paid":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Paid reservations cannot be updated. "
                    "A refund is required before modifying "
                    "the reservation."
                ),
            )

        if payment.payment_status != "pending":
            raise HTTPException(
                status_code=409,
                detail="Booking payment cannot be modified",
            )

        # Update reservation information.
        reservation.guest_full_name = booking_info.guest_full_name
        reservation.guest_email = booking_info.guest_email
        reservation.check_in_date = booking_info.check_in_date
        reservation.check_out_date = booking_info.check_out_date
        reservation.total_price = float(total_price)

        # Since the payment is pending, its amount can be updated.
        payment.amount = float(payment_amount)

        response = BookingResponse(
            user_id=user_id,
            hotel_id=reservation.room_type.hotel_id,
            room_type_id=reservation.room_type_id,
            reservation_id=reservation.reservation_id,
            payment_id=payment.payment_id,
            booking_reference=_booking_reference(reservation.reservation_id),
            status=reservation.status,
        )

        db.commit()
        return response

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to modify reservation",
        ) from exc


def apply_balance(
    db: Session,
    payment_id: int,
    amount: int,
    user_id: int,
) -> PaymentResponse:
    """Apply user balance to a pending booking payment."""

    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Amount must be greater than zero",
        )

    try:
        reservation_id = booking_dao.get_owned_payment_reservation_id(
            db,
            payment_id,
            user_id,
        )

        if reservation_id is None:
            raise HTTPException(
                status_code=404,
                detail="Payment not found",
            )

        # Reset the snapshot created by the ownership lookup.
        db.rollback()

        # Lock order:
        # reservation -> payment -> user balance
        reservation = booking_dao.lock_owned_reservation(
            db,
            reservation_id,
            user_id,
        )

        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail="Payment not found",
            )

        payment = booking_dao.lock_booking_payment(
            db,
            payment_id,
            reservation_id,
        )

        if payment is None:
            raise HTTPException(
                status_code=404,
                detail="Payment not found",
            )

        if payment.payment_type != "booking":
            raise HTTPException(
                status_code=409,
                detail="Payment cannot be completed",
            )

        if reservation.status == "cancelled":
            raise HTTPException(
                status_code=409,
                detail="Payment cannot be completed",
            )

        if payment.payment_status == "paid":
            raise HTTPException(
                status_code=409,
                detail="Payment has already been completed",
            )

        if payment.payment_status != "pending":
            raise HTTPException(
                status_code=409,
                detail="Payment cannot be completed",
            )

        if reservation.status != "confirmed":
            raise HTTPException(
                status_code=409,
                detail="Payment cannot be completed",
            )

        # Lock first, then read the current balance.
        balance_row = user_dao.lock_user_balance(
            db=db,
            user_id=user_id,
        )

        if balance_row is None:
            raise HTTPException(
                status_code=404,
                detail="User balance not found",
            )

        user_balance = balance_row.balance

        if user_balance < amount:
            raise HTTPException(
                status_code=409,
                detail="Not enough balance",
            )

        if amount >= payment.amount:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Balance amount must be less than " "the remaining payment amount"
                ),
            )

        balance_row.balance -= amount
        payment.amount -= amount

        result = PaymentResponse(**booking_dao.payment_result(payment))

        db.commit()
        return result

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to apply user balance",
        ) from exc
