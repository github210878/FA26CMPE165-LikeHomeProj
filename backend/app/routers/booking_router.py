from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.repositories import booking_dao
from app.schemas.booking_schema import (
    BookingRequest,
    BookingResponse,
    CancellationResponse,
    PaymentResponse,
)
from app.schemas.reservation_change_schema import (
    ReservationChangeQuoteResponse,
    ReservationChangeReceiptRequest,
    ReservationChangeReceiptResponse,
    ReservationChangeReviewRequest,
)
from app.schemas.reservation_change_payment_schema import (
    AdjustmentSettlementRequest,
    AdjustmentSettlementResponse,
    ReservationFinancialSummary,
)
from app.services import booking_service, reservation_change_service, reservation_change_payment_service
from app.utilities.auth import get_current_user_id

router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"],
)


class _ChangeContractRoute(APIRoute):
    """Keep signed quotes and request bodies out of validation error responses."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_validation(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise HTTPException(status_code=422, detail=[
                    {key: error[key] for key in ("loc", "msg", "type")}
                    for error in exc.errors()
                ]) from exc

        return safe_validation


def confirm_reservation_change(
    change_info: ReservationChangeReceiptRequest,
    reservation_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Confirm an accepted signed review, or return its exact committed receipt."""
    return reservation_change_service.confirm_reservation_change(db, change_info, reservation_id, user_id)


def pay_reservation_change_adjustment(
    payment_info: AdjustmentSettlementRequest,
    reservation_id: int = Path(gt=0),
    adjustment_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Record payment of an owned, reviewed internal charge; no bank transaction."""
    owned = booking_dao.get_owned_change_adjustment(db, adjustment_id, user_id)
    if owned is None or owned[2].reservation_id != reservation_id:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return reservation_change_payment_service.settle_reservation_change_charge(
        db, payment_info, adjustment_id, user_id,
    )


def get_reservation_financial_summary(
    reservation_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Read the owner's stay obligation and separate historical ledger buckets."""
    return reservation_change_payment_service.get_reservation_financial_summary(db, reservation_id, user_id)


router.add_api_route(
    "/{reservation_id}/change-confirm", confirm_reservation_change,
    methods=["POST"], response_model=ReservationChangeReceiptResponse,
    route_class_override=_ChangeContractRoute,
)
router.add_api_route(
    "/{reservation_id}/adjustments/{adjustment_id}/pay", pay_reservation_change_adjustment,
    methods=["POST"], response_model=AdjustmentSettlementResponse,
    route_class_override=_ChangeContractRoute,
)
router.add_api_route(
    "/{reservation_id}/financial-summary", get_reservation_financial_summary,
    methods=["GET"], response_model=ReservationFinancialSummary,
    route_class_override=_ChangeContractRoute,
)


@router.post("/{reservation_id}/change-quote", response_model=ReservationChangeQuoteResponse)
def quote_reservation_change(
    reservation_id: int,
    change_info: ReservationChangeReviewRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Review trusted revised pricing without changing reservation/payment records."""
    return reservation_change_service.quote_reservation_change(db, change_info, reservation_id, user_id)


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


@router.get("/get-all-bookings")
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
        raise HTTPException(status_code=422, detail="Payment request must not contain a body")
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
