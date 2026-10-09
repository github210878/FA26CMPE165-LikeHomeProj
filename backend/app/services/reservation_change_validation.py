"""Side-effect-free guards for future reservation-change operations.

No database lookup, overlap query, provider call, mutation, or settlement occurs
here. Future callers must load owner-scoped records and recheck under locks
before committing. Quote reviews and their owner IDs must come from the server.
"""

from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.hotel import Hotel
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room_type import RoomType
from app.schemas import booking_schema
from app.schemas.hotel_schema import HotelRevalidationRequest, HotelRevalidationResponse
from app.schemas.reservation_change_schema import (
    ReservationChangeConfirmRequest,
    ReservationChangeQuoteRequest,
    ReservationChangeQuoteResponse,
    ReservationChangeRevalidationContext,
)
from app.services.booking_service import _money


def validate_reservation_change_eligibility(
    reservation: Reservation | None,
    payments: Sequence[Payment],
    user_id: int,
    *,
    today: date | None = None,
) -> Payment:
    """Return the single eligible booking payment without altering its state."""
    if reservation is None or reservation.user_id != user_id:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status != "confirmed":
        raise HTTPException(status_code=409, detail="Reservation cannot be changed")
    calendar_today = today if today is not None else booking_schema.date.today()
    if reservation.check_in_date <= calendar_today:
        raise HTTPException(status_code=409, detail="Only upcoming reservations can be changed")
    if reservation.check_out_date <= reservation.check_in_date:
        raise HTTPException(status_code=409, detail="Reservation dates are invalid")
    if (
        len(payments) != 1
        or payments[0].reservation_id != reservation.reservation_id
        or payments[0].payment_type != "booking"
        or payments[0].payment_status not in ("pending", "paid")
    ):
        raise HTTPException(status_code=409, detail="Reservation payment state is unsupported or ambiguous")
    return payments[0]


def validate_changed_dates(
    reservation: Reservation, request: ReservationChangeQuoteRequest,
) -> None:
    """The request schema checks calendar/order; the record supplies the old dates."""
    if (
        request.check_in_date == reservation.check_in_date
        and request.check_out_date == reservation.check_out_date
    ):
        raise HTTPException(status_code=422, detail="Requested dates must differ from the existing stay")


def build_change_revalidation_request(
    reservation: Reservation,
    room_type: RoomType | None,
    hotel: Hotel | None,
    request: ReservationChangeQuoteRequest,
    context: ReservationChangeRevalidationContext | None,
) -> HotelRevalidationRequest:
    """Use the owned record's property and explicit context, without a provider call.

    Call only after eligibility/ownership validation. Missing historical context
    fails closed; no guest count or destination is inferred from a room/quote.
    """
    validate_changed_dates(reservation, request)
    if (
        room_type is None or hotel is None
        or room_type.room_type_id != reservation.room_type_id
        or hotel.hotel_id != room_type.hotel_id
    ):
        raise HTTPException(status_code=409, detail="Reservation property context is unavailable")
    if context is None:
        raise HTTPException(status_code=409, detail="Reservation revalidation context must be established")
    try:
        return HotelRevalidationRequest(
            property_token=hotel.hotel_token,
            check_in_date=request.check_in_date,
            check_out_date=request.check_out_date,
            **context.model_dump(),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail="Reservation revalidation context is invalid") from exc


def validate_change_quote_acceptance(
    request: ReservationChangeConfirmRequest,
    reviewed_quote: ReservationChangeQuoteResponse | None,
    fresh_quote: HotelRevalidationResponse,
    *,
    reservation_id: int,
    user_id: int,
    quote_owner_user_id: int,
    now: datetime | None = None,
) -> None:
    """Check a server-held review against acceptance and a fresh provider quote.

    The caller must establish eligibility and derive the property/context from
    the owned reservation before obtaining fresh_quote. This guard neither
    issues quotes nor implements a confirmation operation.
    """
    current_time = now if now is not None else datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("Quote validation requires a timezone-aware clock")
    if (
        reviewed_quote is None
        or quote_owner_user_id != user_id
        or reviewed_quote.reservation_id != reservation_id
        or reviewed_quote.quote_id != request.quote_id
        or reviewed_quote.expires_at <= current_time
    ):
        raise HTTPException(status_code=409, detail="Change quote is invalid or expired; review a new quote")
    previous = reviewed_quote.quote
    for quote in (previous, fresh_quote):
        if (
            quote.check_in_date != request.check_in_date
            or quote.check_out_date != request.check_out_date
        ):
            raise HTTPException(status_code=409, detail="Change quote does not match the requested dates")
    context_fields = ("property_token", "adults", "children", "currency", "number_of_nights")
    price_fields = (
        "current_price_per_night", "provider_base_total",
        "likehome_reservation_total", "likehome_payment_amount",
    )
    if (
        any(getattr(previous, field) != getattr(fresh_quote, field) for field in context_fields)
        or any(
            _money(Decimal(str(getattr(previous, field)))) != _money(Decimal(str(getattr(fresh_quote, field))))
            for field in price_fields
        )
        or _money(Decimal(str(request.price_per_night))) != _money(Decimal(str(fresh_quote.current_price_per_night)))
        or _money(Decimal(str(request.accepted_payment_amount))) != _money(Decimal(str(fresh_quote.likehome_payment_amount)))
    ):
        raise HTTPException(status_code=409, detail="Rate changed; revalidate and review the current quote")
