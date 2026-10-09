"""Read-only reservation-change review. Confirmation/mutation is deferred."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories import booking_dao
from app.schemas.reservation_change_schema import (
    ReservationChangeQuoteResponse,
    ReservationChangeReviewRequest,
    ReservationChangeRevalidationContext,
)
from app.services import hotel_service
from app.services.reservation_change_validation import (
    build_change_revalidation_request,
    validate_reservation_change_eligibility,
)
from app.utilities.reservation_change_quote import (
    ensure_change_quote_signing_configured,
    issue_reservation_change_quote,
)


def quote_reservation_change(
    db: Session, request: ReservationChangeReviewRequest, reservation_id: int, user_id: int,
) -> ReservationChangeQuoteResponse:
    records = booking_dao.get_owned_reservation_for_change(db, reservation_id, user_id)
    if records is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    reservation, room_type, hotel, payments = records
    payment = validate_reservation_change_eligibility(reservation, payments, user_id)
    context = ReservationChangeRevalidationContext(**request.model_dump(exclude={"check_in_date", "check_out_date"}))
    info = build_change_revalidation_request(reservation, room_type, hotel, request, context)
    if booking_dao.check_if_user_booked_by_date_range(
        db, user_id, info.check_in_date, info.check_out_date, exclude_reservation_id=reservation_id,
    ):
        raise HTTPException(status_code=400, detail="User already has a booking that overlaps with the given date.")
    # This precheck does not reserve dates. Confirmation must repeat it under locks.
    ensure_change_quote_signing_configured()
    quote = hotel_service.revalidate_hotel(info)
    return issue_reservation_change_quote(
        reservation=reservation, room_type=room_type, hotel=hotel, payment=payment,
        user_id=user_id, context=info, quote=quote,
    )
