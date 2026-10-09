from sqlalchemy import Float, String, Integer, Date, DateTime, Enum, Index
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.orm import Mapped, mapped_column
from app.config.database import Base
from datetime import date, datetime


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_user_dates", "user_id", "check_in_date", "check_out_date"),
    )

    reservation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    room_type_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Persistence only: services will increment this in a later increment.
    revision: Mapped[int] = mapped_column(
        Integer().with_variant(INTEGER(unsigned=True), "mysql"),
        default=0, server_default="0", nullable=False,
    )

    # Nullable so reservations created before migration 003 remain readable.
    guest_full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    guest_email: Mapped[str | None] = mapped_column(String(100), nullable=True)

    check_in_date: Mapped[date] = mapped_column(Date, nullable=False)

    check_out_date: Mapped[date] = mapped_column(Date, nullable=False)

    total_price: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[str] = mapped_column(
        Enum("confirmed", "cancelled", "completed"), default="confirmed", nullable=False
    )

    created_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.now)
