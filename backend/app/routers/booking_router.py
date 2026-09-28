from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.booking_schema import (
    BookingRequest,
)
from app.services import user_service
from app.utilities.auth import get_current_user_id
from app.services import booking_service
from app.utilities.auth import get_current_user_id

router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"],
    dependencies=[Depends(get_current_user_id)],
)


@router.post("/create")
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


@router.get("/get-all-payments")
def get_all_payments(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    Retrieve all payments for the current user.
    """
    return booking_service.get_all_payments_by_user_id(db, user_id)


@router.get("/get-booking-details/{reservation_id}")
def get_booking_details(reservation_id: int, db: Session = Depends(get_db)):
    """
    Retrieve booking details for a specific booking ID.
    """
    return booking_service.get_booking_by_id(db, reservation_id)


@router.get("/get-payment-details/{payment_id}")
def get_payment_details(payment_id: int, db: Session = Depends(get_db)):
    """
    Retrieve payment details for a specific payment ID.
    """
    return booking_service.get_payment_by_id(db, payment_id)


@router.post("/cancel-booking/{reservation_id}")
def cancel_booking(reservation_id: int, db: Session = Depends(get_db)):
    """
    Cancel a booking for the current user.
    """
    return booking_service.cancel_booking(db, reservation_id)
