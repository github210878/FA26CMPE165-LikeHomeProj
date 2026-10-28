from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.user import User
from app.repositories import booking_dao

MONEY_CENT = Decimal("0.01")
MAX_MONEY = Decimal("99999999.99")


class PaymentProvider(Protocol):
    """Boundary for a future external payment provider."""

    def authorize(self, payment: Payment) -> None: ...


class LocalPaymentProvider:
    """Complete payments locally until an external provider is introduced."""

    def authorize(self, payment: Payment) -> None:
        return None


class PaymentService:
    def __init__(self, provider: PaymentProvider | None = None):
        self.provider = provider or LocalPaymentProvider()

    def create_pending_payment(
        self, db: Session, reservation_id: int, amount: float
    ) -> Payment:
        return booking_dao.stage_booking_record(
            db,
            Payment(
                reservation_id=reservation_id,
                amount=amount,
                payment_type="booking",
                payment_status="pending",
            ),
        )

    def complete_booking_payment(
        self, db: Session, user: User, reservation: Reservation, payment: Payment
    ) -> bool:
        if payment.payment_type != "booking" or reservation.status == "cancelled":
            raise HTTPException(status_code=409, detail="Payment cannot be completed")
        if payment.payment_status not in ("pending", "paid"):
            raise HTTPException(status_code=409, detail="Payment cannot be completed")

        points = self.reward_points_for(payment.amount)
        if payment.payment_status == "paid":
            return False
        if reservation.status != "confirmed":
            raise HTTPException(status_code=409, detail="Payment cannot be completed")
        self.provider.authorize(payment)
        payment.payment_status = "paid"
        booking_dao.add_reward_points_to_user(db, user, points=points)
        return True

    def create_cancellation_payment(
        self, db: Session, reservation_id: int, amount: float
    ) -> Payment:
        return booking_dao.stage_booking_record(
            db,
            Payment(
                reservation_id=reservation_id,
                amount=amount,
                payment_type="cancellation",
                payment_status="pending",
            ),
        )

    @staticmethod
    def reward_points_for(amount: float | Decimal) -> int:
        try:
            if isinstance(amount, bool) or not isinstance(
                amount, (int, float, Decimal)
            ):
                raise ValueError("Payment amount is not numeric")
            value = Decimal(str(amount))
            if (
                not value.is_finite()
                or value < 0
                or value > MAX_MONEY
                or value != value.quantize(MONEY_CENT)
            ):
                raise ValueError("Payment amount is outside supported cents")
            return int(value.to_integral_value(rounding=ROUND_FLOOR))
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(
                status_code=409, detail="Payment amount is unsupported"
            ) from exc


payment_service = PaymentService()
