from tokenize import String
from sqlalchemy import Float, String, Integer, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column
from app.config.database import Base
from datetime import datetime


class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    room_type_id: Mapped[int] = mapped_column(Integer, nullable=False)

    check_in_date: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    check_out_date: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    total_price: Mapped[float] = mapped_column(Float, nullable=False)

    status: Mapped[str] = mapped_column(
        Enum("confirmed", "cancelled", "completed"), default="confirmed", nullable=False
    )

    created_at: Mapped[DateTime] = mapped_column(DateTime, default=datetime.now)
