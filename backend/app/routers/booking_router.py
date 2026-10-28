from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.booking_schema import (
    BookingListItem,
    BookingRequest,
    BookingResponse,
    CancellationResponse,
    PaymentResponse,
)
from app.schemas.reservation_change_payment_schema import ReservationFinancialSummary
from app.schemas.reservation_change_schema import (
    ReservationChangeQuoteResponse,
    ReservationChangeReviewRequest,
)
from app.services import (
    booking_service,
    reservation_change_quote_service,
    reservation_financial_summary_service,
)
from app.utilities.auth import get_current_user_id

router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"],
)


async def _financial_summary_read_request(request: Request) -> None:
    if request.query_params or await request.body():
        raise HTTPException(
            status_code=422,
            detail="Financial summary accepts no query parameters or body",
        )


@router.get(
    "/{reservation_id}/financial-summary", response_model=ReservationFinancialSummary
)
def get_reservation_financial_summary(
    reservation_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    _request: None = Depends(_financial_summary_read_request),
):
    """Read this customer's pre-change financial state; revision 0 is a convention."""
    return reservation_financial_summary_service.get_financial_summary(
        db, reservation_id, user_id
    )


@router.post(
    "/{reservation_id}/change-quote", response_model=ReservationChangeQuoteResponse
)
def quote_reservation_change(
    reservation_id: int,
    review: ReservationChangeReviewRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Review a same-property date change; this does not change or hold a booking."""
    return reservation_change_quote_service.create_change_quote(
        db, reservation_id, review, user_id
    )


@router.post("/create", response_model=BookingResponse)
def create_booking(
    booking_info: BookingRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Create a new booking for the current user.
    This function checks if the user already has a booking that overlaps with the given date range.
    If the user has an overlapping booking, it raises an HTTPException.
    Otherwise, it creates a new hotel, room type, reservation, and payment record in the database.
    """
    return booking_service.create_booking(db, booking_info, user_id)


@router.get("/get-all-bookings", response_model=list[BookingListItem])
def get_all_bookings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Retrieve all bookings for the current user.
    """
    return booking_service.get_all_booking_by_user_id(db, user_id)


@router.get("/get-all-payments", response_model=list[PaymentResponse])
def get_all_payments(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Retrieve all payments for the current user.
    """
    return booking_service.get_all_payments_by_user_id(db, user_id)


@router.get("/get-booking-details/{reservation_id}")
def get_booking_details(
    reservation_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Retrieve booking details for a specific booking ID.
    """
    return booking_service.get_booking_by_id(db, reservation_id, user_id)


@router.get("/get-payment-details/{payment_id}", response_model=PaymentResponse | None)
def get_payment_details(
    payment_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Retrieve payment details for a specific payment ID.
    """
    return booking_service.get_payment_by_id(db, payment_id, user_id)


@router.post("/pay/{payment_id}", response_model=PaymentResponse)
def pay_booking_payment(
    payment_id: int,
    body: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Record an internal LikeHome payment for the current user's reservation."""
    if body is not None:
        raise HTTPException(
            status_code=422, detail="Payment request must not contain a body"
        )
    return booking_service.pay_booking_payment(db, payment_id, user_id)


@router.post("/cancel-booking/{reservation_id}", response_model=CancellationResponse)
def cancel_booking(
    reservation_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Cancel a booking for the current user.
    """
    return booking_service.cancel_booking(db, reservation_id, user_id)


@router.post("/pay-cancellation-fee/{payment_id}", response_model=PaymentResponse)
def pay_cancellation_fee(
    payment_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Pay cancellation payment"""
    return booking_service.pay_cancellation_fee(
        db, payment_id=payment_id, user_id=user_id
    )


@router.get("/pay-with-reward-points/{payment_id}")
def pay_with_reward_points(
    payment_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    return booking_service.pay_with_reward_points(
        db=db, user_id=user_id, payment_id=payment_id
    )
