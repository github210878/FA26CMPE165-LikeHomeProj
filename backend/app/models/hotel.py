from tokenize import String
from sqlalchemy import String, Integer, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column
from app.config.database import Base


class Hotel(Base):
    __tablename__ = "hotels"

    hotel_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    hotel_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    description: Mapped[str | None] = mapped_column(String(5000))

    street: Mapped[str | None] = mapped_column(String(255))

    city: Mapped[str | None] = mapped_column(String(100))

    country: Mapped[str | None] = mapped_column(String(100))

    state: Mapped[str | None] = mapped_column(String(100))

    zip_code: Mapped[str | None] = mapped_column(String(20))

    phone: Mapped[str | None] = mapped_column(String(100))
