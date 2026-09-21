from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)

    full_name: Mapped[str | None] = mapped_column(String(100))

    phone: Mapped[str | None] = mapped_column(String(30))

    reward_points: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    status: Mapped[str] = mapped_column(Enum("active", "deleted"), default="active")
