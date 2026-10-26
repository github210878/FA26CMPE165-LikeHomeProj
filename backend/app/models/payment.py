from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class Payment(Base):
    __tablename__ = "payments"

    payment_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    reservation_id: Mapped[int] = mapped_column(Integer, nullable=False)

    amount: Mapped[float] = mapped_column(Float, nullable=False)

    payment_type: Mapped[str] = mapped_column(
        Enum("booking", "cancellation"), nullable=False
    )

    payment_status: Mapped[str] = mapped_column(
        Enum("pending", "paid", "failed", "refunded"), default="pending", nullable=False
    )

    created_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.now)
