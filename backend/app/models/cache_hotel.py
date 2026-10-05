from sqlalchemy import DECIMAL, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from decimal import Decimal
from app.config.database import Base


class CacheHotel(Base):
    __tablename__ = "cache_hotels"

    property_token: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    price_per_night: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 2),
        nullable=True,
    )

    rating: Mapped[Decimal | None] = mapped_column(
        DECIMAL(3, 2),
        nullable=True,
    )

    amenities: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )

    hotel_class: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    overall_rating: Mapped[Decimal | None] = mapped_column(
        DECIMAL(3, 2),
        nullable=True,
    )

    reviews: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    rate_per_night: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    total_rate: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    thumbnail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    link: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    gps_coordinates: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
