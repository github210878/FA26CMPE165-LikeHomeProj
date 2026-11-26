from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    room_type_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nullable so reservations created before migration 003 remain readable.
    guest_full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    guest_email: Mapped[str | None] = mapped_column(String(100), nullable=True)

    check_in_date: Mapped[date] = mapped_column(Date, nullable=False)

    check_out_date: Mapped[date] = mapped_column(Date, nullable=False)

    total_price: Mapped[float] = mapped_column(Float, nullable=False)

    # Null for bookings made before the original provider search context was saved.
    booking_context: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)

    status: Mapped[str] = mapped_column(
        Enum("confirmed", "cancelled", "completed"), default="confirmed", nullable=False
    )

    created_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.now)
