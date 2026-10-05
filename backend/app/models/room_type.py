from tokenize import String
from sqlalchemy import Float, String, Integer, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column
from app.config.database import Base


class RoomType(Base):
    __tablename__ = "room_types"

    room_type_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    hotel_id: Mapped[int] = mapped_column(Integer, nullable=False)

    type_name: Mapped[str] = mapped_column(String(100), nullable=False)

    description: Mapped[str | None] = mapped_column(String(500))

    price_per_night: Mapped[float] = mapped_column(Float, nullable=False)
