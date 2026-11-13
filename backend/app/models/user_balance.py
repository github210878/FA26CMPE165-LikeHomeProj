from sqlalchemy import Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class UserBalance(Base):
    __tablename__ = "user_balances"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    balance: Mapped[float] = mapped_column(Float, nullable=False)
